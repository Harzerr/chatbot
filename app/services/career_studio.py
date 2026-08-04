import asyncio
import ipaddress
import json
import re
import socket
from html import unescape
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

from firecrawl import FirecrawlApp
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CareerStudioService:
    def __init__(self) -> None:
        self._model = settings.CAREER_LLM_MODEL or settings.LLM_MODEL
        self._llm = ChatOpenAI(
            model=self._model,
            temperature=0,
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_API_BASE,
        )

    async def extract_facts(self, resume_text: str) -> list[dict[str, Any]]:
        prompt = f"""Extract only explicit, verifiable career facts from this resume.
Return JSON only: {{"facts":[{{"fact_type":"experience|project|skill|education|certificate|award|language|other","title":"中文事实标题","content":{{"summary":"中文事实摘要","highlights":["中文事实要点"]}},"tags":["中文标签"],"evidence":"exact source excerpt","is_verified":false}}]}}.
除公司名、学校名、产品名、技术名词、证书或竞赛官方名称外，title、summary、highlights 和 tags 必须使用中文；不要输出英文解释或英文分类名称。evidence 保留简历原文。
Never invent details, metrics, employers, dates, skills, or qualifications. Keep each fact atomic, but do not split one project or work experience into separate title and content facts. For every project or experience, use one fact: title is the project/company name, content.summary contains the overview and role, and content.highlights contains the concrete work and results. Do not create a fact containing only a title, date, role, or isolated bullet when it belongs to the same project or experience.

RESUME:
{resume_text[:18000]}"""
        payload = await self._invoke_json(prompt)
        return payload.get("facts", []) if isinstance(payload.get("facts"), list) else []

    async def normalize_job(self, raw_content: str, source_url: str | None) -> dict[str, Any]:
        prompt = f"""Convert this job description into JSON only. Use this shape:
{{"title":"","company":"","location":"","employment_type":"","seniority":"","responsibilities":[""],"required_skills":[""],"preferred_skills":[""],"education_requirements":[""],"language_requirements":[""],"keywords":[""],"summary":""}}.
Separate strict requirements from preferred qualifications. Use empty strings or arrays where information is absent. Do not infer unsupported facts.
SOURCE URL: {source_url or "not provided"}
JOB DESCRIPTION:
{raw_content[:30000]}"""
        result = await self._invoke_json(prompt)
        return {
            "title": str(result.get("title") or ""),
            "company": str(result.get("company") or ""),
            "location": str(result.get("location") or ""),
            "employment_type": str(result.get("employment_type") or ""),
            "seniority": str(result.get("seniority") or ""),
            "responsibilities": self._string_list(result.get("responsibilities")),
            "required_skills": self._string_list(result.get("required_skills")),
            "preferred_skills": self._string_list(result.get("preferred_skills")),
            "education_requirements": self._string_list(result.get("education_requirements")),
            "language_requirements": self._string_list(result.get("language_requirements")),
            "keywords": self._string_list(result.get("keywords")),
            "summary": str(result.get("summary") or ""),
        }

    async def generate_tailored_resume(
        self,
        job: dict[str, Any],
        facts: list[dict[str, Any]],
        has_profile_education: bool = False,
    ) -> dict[str, Any]:
        prompt = f"""Create a tailored resume JSON for the job below using only the supplied verified facts.
Return JSON only in this shape:
{{"headline":"","summary":"","sections":[{{"heading":"实习经历","entries":[{{"fact_ids":[1],"title":"公司或项目名称","subtitle":"岗位或角色","period":"起止时间","summary":"项目或职责简介","tech_stack":[""],"items":[{{"fact_ids":[1],"label":"成果标签","text":"具体事实表述"}}]}}]}},{{"heading":"项目经历","entries":[]}},{{"heading":"专业技能","items":[{{"fact_ids":[1],"label":"","text":""}}]}},{{"heading":"竞赛与荣誉","items":[]}}],"skills":[],"match_analysis":{{"matched_requirements":[""],"gaps":[""],"selected_fact_ids":[1]}}}}.
Every item must cite one or more fact_ids. Do not add any unprovided achievement, tool, employer, date, credential, or metric. State gaps rather than filling them.
Use only these dynamic sections when supported by verified facts: 实习经历, 项目经历, 专业技能, 竞赛与荣誉. Each section heading must be exactly one of those four strings. Never join headings with "|", "/", "、", or any other separator. {"Do not generate 教育背景 because it is maintained as fixed personal-profile information." if has_profile_education else "Include 教育背景 only when supported by verified facts."}
The evidence field is the full source of truth and often contains a richer original resume description than content.summary/highlights. For every selected experience or project, preserve the material technical method, scenario, result, metric, and exception/fallback details stated in evidence. Do not compress a detailed source bullet into a metric-only or slogan-like sentence. When evidence has multiple original bullets, map each distinct original bullet to an item instead of discarding it. Use 3-4 detailed highlights when the source supports them; one highlight may be 70-180 Chinese characters when needed to retain the original technical chain. Do not force the resume onto one page.
For 实习经历 and 项目经历, always use entries and follow this display structure: title/company on the left, role/degree in the middle, period on the right, then a 项目简介 or 个人职责与成果, 技术栈, and detailed 技术亮点/核心成果. Do not leave fields blank if the supplied fact explicitly contains the value; do not infer a missing value. Do not put an entire experience into one bullet.
Order internship and project entries by relevance to the target role, then recency. Tailoring may reorder and emphasize evidence, but must not delete substantive source details from any selected experience. For 竞赛与荣誉, select at most five high-value, evidenced items; order international/national awards before provincial awards, then scholarships and other honors. Make the headline a concise target role, and keep every bullet specific to the target job.
JOB:
{json.dumps(job, ensure_ascii=False)}
VERIFIED FACTS:
{json.dumps(facts, ensure_ascii=False)}"""
        return await self._invoke_json(prompt)

    async def fetch_job_page(self, source_url: str) -> str:
        parsed = urlparse(source_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("Only public http(s) job URLs are supported")
        self._ensure_public_host(parsed.hostname)
        if settings.FIRECRAWL_API_KEY:
            try:
                rendered_text = await asyncio.to_thread(self._fetch_rendered_page, source_url)
                if self._looks_like_job_description(rendered_text):
                    return rendered_text[:50000]
            except Exception:
                # A static fallback still handles plain HTML pages when the rendering provider is unavailable.
                pass

        static_text = await asyncio.to_thread(self._fetch_page, source_url)
        if not self._looks_like_job_description(static_text):
            raise ValueError("The page did not expose a job description. Paste the JD text or retry after the page is publicly accessible.")
        return static_text

    def _fetch_rendered_page(self, source_url: str) -> str:
        result = FirecrawlApp(api_key=settings.FIRECRAWL_API_KEY).scrape_url(source_url, formats=["markdown"])
        if isinstance(result, dict):
            text = result.get("markdown") or (result.get("data") or {}).get("markdown") or ""
        else:
            text = getattr(result, "markdown", "") or getattr(getattr(result, "data", None), "markdown", "") or ""
        text = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", str(text))
        return re.sub(r"\s+", " ", unescape(text)).strip()

    def _fetch_page(self, source_url: str) -> str:
        opener = build_opener(_NoRedirect())
        request = Request(source_url, headers={"User-Agent": "Mozilla/5.0 (compatible; CareerStudio/1.0)"})
        with opener.open(request, timeout=12) as response:
            if response.status < 200 or response.status >= 300:
                raise ValueError(f"Job page returned HTTP {response.status}")
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "text/plain"}:
                raise ValueError("Job page did not return readable text")
            body = response.read(1_500_001)
        if len(body) > 1_500_000:
            raise ValueError("Job page is too large")
        text = body.decode("utf-8", errors="ignore")
        if content_type == "text/html":
            text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", text)
            text = re.sub(r"(?s)<[^>]+>", " ", text)
        text = re.sub(r"\s+", " ", unescape(text)).strip()
        if len(text) < 80:
            raise ValueError("Job page did not contain enough readable text; paste the job description instead")
        return text[:50000]

    def _ensure_public_host(self, hostname: str) -> None:
        try:
            addresses = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        except socket.gaierror as exc:
            raise ValueError("Could not resolve the job URL host") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address[4][0])
            if not ip.is_global:
                raise ValueError("Job URL must resolve only to public network addresses")

    @staticmethod
    def _looks_like_job_description(text: str) -> bool:
        content = text.lower()
        markers = (
            "岗位职责", "工作职责", "职位描述", "岗位要求", "职位要求", "任职要求", "任职资格",
            "responsibilities", "qualifications", "job description", "requirements",
        )
        return len(text) >= 300 and any(marker in content for marker in markers)

    async def _invoke_json(self, prompt: str) -> dict[str, Any]:
        try:
            response = await self._llm.ainvoke([HumanMessage(content=prompt)])
        except Exception as exc:
            if "not available in your region" in str(exc).lower() and self._model != "openrouter/auto":
                try:
                    fallback = ChatOpenAI(
                        model="openrouter/auto",
                        temperature=0,
                        api_key=settings.OPENROUTER_API_KEY,
                        base_url=settings.OPENROUTER_API_BASE,
                    )
                    response = await fallback.ainvoke([HumanMessage(content=prompt)])
                except Exception as fallback_exc:
                    raise ValueError("The configured AI model is unavailable. Set CAREER_LLM_MODEL to a model available in your OpenRouter region.") from fallback_exc
            else:
                raise ValueError("The AI service is unavailable. Check CAREER_LLM_MODEL and the OpenRouter account configuration.") from exc
        content = response.content if hasattr(response, "content") else str(response)
        if isinstance(content, list):
            content = "".join(part.get("text", "") if isinstance(part, dict) else str(part) for part in content)
        cleaned = str(content).strip()
        candidates = [cleaned]
        fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.IGNORECASE | re.DOTALL)
        if fenced:
            candidates.append(fenced.group(1))
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            candidates.append(cleaned[start:end + 1])

        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, dict):
                return parsed
        raise ValueError("The AI response was not valid JSON. Please retry.")

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()][:50]
