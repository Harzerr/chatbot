import asyncio
import hashlib
import ipaddress
import json
import re
import socket
from html import unescape
from pathlib import Path
from time import perf_counter
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPRedirectHandler

from firecrawl import FirecrawlApp
from langchain_core.messages import HumanMessage
from langchain_openai import ChatOpenAI

from app.core.config import settings
from app.services.task_queue import get_redis_connection
from app.utils.logger import setup_logger

logger = setup_logger(__name__)
RESUME_OPTIMIZER_SKILL_PATH = Path(__file__).resolve().parents[2] / "resume-optimizer-skill" / "SKILL.md"


_FACT_TYPE_ALIASES = {
    "实习经历": "experience",
    "工作经历": "experience",
    "项目经历": "project",
    "专业技能": "skill",
    "教育背景": "education",
    "证书": "certificate",
    "竞赛与荣誉": "award",
    "语言能力": "language",
    "其他": "other",
}
_FACT_TAG_ALIASES = {
    "education": "教育背景",
    "experience": "经历",
    "internship": "实习经历",
    "project": "项目经历",
    "skill": "专业技能",
    "certificate": "证书",
    "award": "竞赛与荣誉",
    "language": "语言能力",
    "master": "硕士",
    "bachelor": "本科",
    "phd": "博士",
    "research": "科研经历",
    "work": "工作经历",
}


def _load_resume_optimizer_skill() -> str:
    try:
        skill = RESUME_OPTIMIZER_SKILL_PATH.read_text(encoding="utf-8")
        logger.info("Loaded resume optimizer skill path=%s chars=%s", RESUME_OPTIMIZER_SKILL_PATH, len(skill))
        return skill
    except OSError as exc:
        logger.warning("Resume optimizer skill is unavailable at %s: %s", RESUME_OPTIMIZER_SKILL_PATH, exc)
        return "仅使用原文明确证据；不得编造数字、技术、角色或结果；项目摘要和要点必须适合技术简历。"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CareerStudioService:
    def __init__(self) -> None:
        self._model = settings.CAREER_LLM_MODEL or settings.LLM_MODEL
        self._llm = ChatOpenAI(
            model=self._model,
            temperature=0,
            max_tokens=max(settings.CAREER_LLM_MAX_TOKENS, 1600),
            timeout=settings.CAREER_LLM_TIMEOUT,
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_API_BASE,
        )
        self._resume_llm = ChatOpenAI(
            model=self._model,
            temperature=0,
            max_tokens=max(settings.CAREER_RESUME_MAX_TOKENS, 2400),
            timeout=settings.CAREER_RESUME_TIMEOUT,
            api_key=settings.OPENROUTER_API_KEY,
            base_url=settings.OPENROUTER_API_BASE,
        )
        self._resume_optimizer_skill = _load_resume_optimizer_skill()

    @staticmethod
    def _job_cache_key(raw_content: str, source_url: str | None) -> str:
        payload = f"{source_url or ''}\n{raw_content.strip()}".encode("utf-8")
        return f"career-job-normalized:v1:{hashlib.sha256(payload).hexdigest()}"

    def _read_normalized_cache(self, raw_content: str, source_url: str | None) -> dict[str, Any] | None:
        try:
            cached = get_redis_connection().get(self._job_cache_key(raw_content, source_url))
            if cached:
                result = json.loads(cached)
                return result if isinstance(result, dict) else None
        except Exception as exc:
            logger.debug("Career job cache read skipped: %s", exc)
        return None

    def _write_normalized_cache(self, raw_content: str, source_url: str | None, result: dict[str, Any]) -> None:
        try:
            get_redis_connection().setex(
                self._job_cache_key(raw_content, source_url),
                settings.CAREER_JOB_CACHE_TTL_SECONDS,
                json.dumps(result, ensure_ascii=False),
            )
        except Exception as exc:
            logger.debug("Career job cache write skipped: %s", exc)

    async def extract_facts(self, resume_text: str) -> list[dict[str, Any]]:
        prompt = f"""Extract only explicit, verifiable career facts from this resume.
Return JSON only: {{"facts":[{{"fact_type":"experience|project|skill|education|certificate|award|language|other","title":"中文事实标题","content":{{"summary":"中文事实摘要","highlights":["中文事实要点"]}},"tags":["中文标签"],"evidence":"exact source excerpt","is_verified":false}}]}}.
除公司名、学校名、产品名、技术名词、证书或竞赛官方名称外，title、summary、highlights 和 tags 必须使用中文；不要输出英文解释或英文分类名称。evidence 保留简历原文。
Never invent details, metrics, employers, dates, skills, or qualifications. Keep each fact atomic, but do not split one project or work experience into separate title and content facts. For every project or experience, use one fact: title is the project/company name, content.summary contains the overview and role, and content.highlights contains the concrete work and results. Do not create a fact containing only a title, date, role, or isolated bullet when it belongs to the same project or experience.

RESUME:
{resume_text[:18000]}"""
        payload = await self._invoke_json(prompt)
        raw_facts = payload.get("facts", []) if isinstance(payload.get("facts"), list) else []
        normalized_facts = []
        for item in raw_facts:
            if not isinstance(item, dict):
                continue
            normalized = dict(item)
            fact_type = str(normalized.get("fact_type") or "").strip()
            normalized["fact_type"] = _FACT_TYPE_ALIASES.get(fact_type, fact_type)
            tags = normalized.get("tags")
            if isinstance(tags, list):
                normalized["tags"] = [_FACT_TAG_ALIASES.get(str(tag).strip().lower(), str(tag).strip()) for tag in tags if str(tag).strip()]
            normalized_facts.append(normalized)
        return normalized_facts

    async def extract_fact_from_markdown(self, markdown_text: str, file_name: str) -> dict[str, Any]:
        started_at = perf_counter()
        logger.info(
            "Markdown fact extraction started file=%s input_chars=%s skill_chars=%s",
            file_name,
            len(markdown_text),
            len(self._resume_optimizer_skill),
        )
        prompt = f"""从下面的 Markdown 技术文档中提炼一个或多个适合写入优秀技术简历的项目/模块事实，返回 JSON，不要输出 Markdown 代码块。
返回格式必须是：
{{"facts":[{{"fact_type":"project","title":"中文项目/模块标题","content":{{"summary":"一句话项目摘要，包含目标、场景和本人角色","role":"原文明确写出的角色，没有则为空","tech_stack":["原文明确使用的技术"],"highlights":["动作 + 技术方法 + 解决对象 + 结果/影响的简历要点"],"evidence_map":[]}},"tags":["中文标签"],"evidence":"可在原文核查的关键证据摘录","is_verified":false}}]}}

简历优化 Skill：
{self._resume_optimizer_skill}

额外规则：
1. fact_type 必须为 project。若文档属于实习总结或工作总结，按 Markdown 标题、模块边界和职责边界拆分 1-6 个项目事实；每个事实只对应一个模块、系统、平台、服务或链路。title 优先使用原文正式名称（尤其是包含“模块/系统/平台/服务/链路/引擎/工具”的名称），没有正式名时使用“业务对象 + 技术功能”，不得使用“项目一”、公司名或纯技术名代替项目名。
2. summary 控制在 60-120 个中文字符；highlights 输出 4-6 条完整的简历句子，每条 45-130 个中文字符。必须以明确动词开头（如“设计、实现、重构、接入、排查、建设、编写、优化”），按“动作—技术方法—解决对象—结果/验证”组织，至少写清前三项；原文有结果时必须写出结果，每条以句号结尾。禁止输出“接口开发”“负责系统建设”“FastAPI、Redis”等名词短语、残句或技术栈罗列；没有量化结果时写清实现范围或测试验证，不得补造结果。
3. 不要把“技术栈：FastAPI、Redis”单独作为成果；技术栈只填入 tech_stack。不要重复 summary，不要使用“提升了系统性能”“保证稳定性”等无证据结论。
4. 只允许使用文档明确写出的项目、职责、技术、结果和指标，不得补写或推测；没有量化结果就不要强行补数字。
5. title、summary、role、highlights、tags 使用中文；技术名词、产品名和代码标识保留原文。
6. evidence 必须引用原文中能核查事实的内容。evidence_map 由后端根据输入原文自动对齐，你只需返回空数组，不要生成长证据引用，以免截断 JSON。
7. 只输出一个包含 facts 数组的 JSON 对象，不要输出解释、前言、Markdown 标记或 JSON 之外的文本。内容不足以拆分时 facts 只放一个对象。

文件名：{file_name}
MARKDOWN：
{self._prepare_markdown_for_extraction(markdown_text)}"""
        warnings: list[str] = []
        used_fallback = False
        try:
            payload = await self._invoke_json(prompt)
        except ValueError as exc:
            logger.warning("Markdown fact extraction fell back to deterministic parser file=%s error=%s", file_name, exc)
            payload = self._fallback_markdown_fact(markdown_text, file_name)
            warnings.append("AI 提炼暂时不可用，已使用 Markdown 规则生成草稿，请人工核对。")
            used_fallback = True
        if isinstance(payload.get("facts"), list) and payload.get("facts"):
            normalized_facts = []
            for candidate in payload["facts"]:
                if not isinstance(candidate, dict):
                    continue
                content = candidate.get("content") if isinstance(candidate.get("content"), dict) else {}
                title = str(candidate.get("title") or "").strip()
                if not title:
                    continue
                highlights = content.get("highlights") if isinstance(content.get("highlights"), list) else []
                cleaned_highlights = []
                for item in highlights:
                    text = re.sub(r"^(?:[-*•]\s*|\d+[.)]\s*)", "", str(item)).strip()
                    if not text:
                        continue
                    # 模型偶尔返回“接口开发/异常处理”式短语；至少转换为可直接阅读的简历句子。
                    if not re.match(r"^(设计|实现|重构|接入|排查|建设|编写|优化|完成|负责|通过|基于|采用|搭建|开发|维护)", text):
                        text = "完成" + text
                    if text[-1] not in "。；！？.!?":
                        text += "。"
                    cleaned_highlights.append(text)
                normalized_facts.append({
                    "fact_type": "project",
                    "title": title[:255],
                    "content": {
                        "summary": str(content.get("summary") or "").strip(),
                        "role": str(content.get("role") or "").strip(),
                        "tech_stack": [str(item).strip() for item in content.get("tech_stack", []) if str(item).strip()],
                        "highlights": cleaned_highlights,
                        "evidence_map": [],
                    },
                    "tags": [str(item).strip() for item in candidate.get("tags", []) if str(item).strip()],
                    "evidence": str(candidate.get("evidence") or markdown_text[:10000]).strip()[:10000],
                    "is_verified": False,
                })
            if normalized_facts:
                return {"facts": normalized_facts, "_warnings": [], "_quality": {"fact_count": len(normalized_facts)}}
        candidate = payload.get("fact") if isinstance(payload.get("fact"), dict) else payload
        if not isinstance(candidate, dict):
            raise ValueError("AI 未返回有效的项目事实")
        normalized = dict(candidate)
        normalized["fact_type"] = "project"
        normalized["title"] = str(normalized.get("title") or "").strip()
        content = normalized.get("content")
        if not isinstance(content, dict):
            content = {"summary": str(normalized.get("summary") or ""), "highlights": normalized.get("highlights") or []}
        content["summary"] = str(content.get("summary") or "").strip()
        content["role"] = str(content.get("role") or normalized.get("role") or "").strip()
        tech_stack = content.get("tech_stack") or normalized.get("tech_stack") or []
        content["tech_stack"] = [str(item).strip() for item in tech_stack if str(item).strip()] if isinstance(tech_stack, list) else [item.strip() for item in re.split(r"[,，、;；]", str(tech_stack)) if item.strip()]
        highlights = content.get("highlights")
        content["highlights"] = [re.sub(r"^(?:[-*•]\s*|\d+[.)]\s*)", "", str(item)).strip() for item in highlights if str(item).strip()] if isinstance(highlights, list) else []
        evidence_map = content.get("evidence_map") or normalized.get("evidence_map") or []
        source_text = re.sub(r"\s+", " ", markdown_text).strip()
        normalized_evidence_map = self._align_evidence_map(content["highlights"], markdown_text, evidence_map)
        content["evidence_map"] = normalized_evidence_map
        normalized["content"] = content
        if not normalized["title"] or not content["summary"] and not content["highlights"]:
            raise ValueError("Markdown 中没有提取到完整的项目事实，请补充项目目标、职责或技术细节后重试")
        tags = normalized.get("tags")
        normalized["tags"] = [str(tag).strip() for tag in tags if str(tag).strip()] if isinstance(tags, list) else []
        normalized["evidence"] = str(normalized.get("evidence") or markdown_text[:10000]).strip()[:10000]
        normalized["is_verified"] = False
        source_numbers = set(re.findall(r"\d+(?:\.\d+)?\s*%?", markdown_text))
        resume_claims = {
            "title": normalized["title"],
            "summary": content["summary"],
            "role": content["role"],
            "tech_stack": content["tech_stack"],
            "highlights": content["highlights"],
            "tags": normalized["tags"],
        }
        output_numbers = set(re.findall(r"\d+(?:\.\d+)?\s*%?", json.dumps(resume_claims, ensure_ascii=False)))
        unsupported_numbers = sorted(output_numbers - source_numbers)
        if unsupported_numbers:
            warnings.append(f"检测到原文未出现的数字表达（{', '.join(unsupported_numbers[:5])}），请重点核对量化结果。")
        covered_claims = sum(1 for item in normalized_evidence_map if item["source_quote"] in source_text)
        citation_coverage = covered_claims / len(content["highlights"]) if content["highlights"] else 0.0
        if not normalized_evidence_map:
            warnings.append("模型没有返回逐条原文证据映射，当前内容必须人工核对后再确认。")
        elif citation_coverage < 1.0:
            warnings.append(f"仅有 {covered_claims}/{len(content['highlights'])} 条简历要点能定位到原文，请人工核对。")
        if len(content["highlights"]) < 2:
            warnings.append("可直接用于简历的技术要点较少，建议补充本人动作、技术方法和结果。")
        normalized["_quality"] = {
            "citation_coverage": round(citation_coverage, 3),
            "highlight_count": len(content["highlights"]),
            "has_role": bool(content["role"]),
            "has_tech_stack": bool(content["tech_stack"]),
            "unsupported_numbers": unsupported_numbers,
            "requires_review": bool(warnings),
        }
        if warnings:
            normalized["_warnings"] = warnings
        logger.info(
            "Markdown fact extraction completed file=%s elapsed_ms=%.0f fallback=%s highlights=%s citation_coverage=%.3f",
            file_name,
            (perf_counter() - started_at) * 1000,
            used_fallback,
            len(content["highlights"]),
            citation_coverage,
        )
        return normalized

    @staticmethod
    def _fallback_markdown_fact(markdown_text: str, file_name: str) -> dict[str, Any]:
        lines = [re.sub(r"\s+", " ", line).strip() for line in markdown_text.splitlines()]
        heading_pattern = re.compile(r"^#{1,6}\s+(.+?)\s*$")
        bullet_pattern = re.compile(r"^(?:[-*+•]|\d+[.)])\s+(.+)$")
        title = ""
        sections: list[tuple[str, list[str]]] = []
        current_heading = "项目正文"
        current_lines: list[str] = []

        def flush_section() -> None:
            if current_lines:
                sections.append((current_heading, list(current_lines)))

        for line in lines:
            if not line:
                continue
            heading = heading_pattern.match(line)
            if heading:
                flush_section()
                current_lines.clear()
                current_heading = re.sub(r"[`*_]", "", heading.group(1)).strip()
                if not title and current_heading:
                    title = current_heading
                continue
            current_lines.append(re.sub(r"[`*_]", "", line).strip())
        flush_section()
        title = title or Path(file_name).stem or "未命名项目"

        def is_technical_section(heading: str) -> bool:
            normalized = heading.lower().replace(" ", "")
            return any(marker in normalized for marker in ("技术栈", "techstack", "依赖", "运行环境", "环境要求"))

        paragraphs: list[str] = []
        highlights: list[str] = []
        role_candidates: list[tuple[str, str]] = []
        tech_source: list[str] = []
        for heading, section_lines in sections:
            if is_technical_section(heading):
                tech_source.extend(section_lines)
                continue
            bullet: str | None = None
            for line in section_lines:
                matched = bullet_pattern.match(line)
                if matched:
                    if bullet:
                        highlights.append(bullet)
                    bullet = matched.group(1).strip()
                elif bullet:
                    bullet = f"{bullet} {line}".strip()
                elif line:
                    paragraphs.append(line)
                if re.search(r"(?:角色|职位|担任|负责|实习生|工程师)", line):
                    role_candidates.append((heading, re.sub(r"^(?:角色|职位)\s*[:：]\s*", "", line).strip()))
            if bullet:
                highlights.append(bullet)
        if not highlights:
            highlights = paragraphs[1:]
        highlights = [re.sub(r"\s+", " ", item).strip() for item in highlights if item.strip()]
        highlights = list(dict.fromkeys(highlights))[:8]
        summary_parts = paragraphs[:2] or highlights[:1]
        summary = " ".join(summary_parts).strip() or "请根据 Markdown 原文补充项目摘要。"
        role = next(
            (candidate for heading, candidate in role_candidates if re.search(r"(?:角色|职位|职责|团队分工|我的角色)", heading)),
            role_candidates[0][1] if role_candidates else "",
        )

        tech_text = " ".join(tech_source + [line for line in lines if re.search(r"技术栈|tech stack|技术选型", line, re.IGNORECASE)])
        tags = re.findall(r"(?<![\u4e00-\u9fff])[A-Za-z][A-Za-z0-9+#.-]{1,30}", tech_text or markdown_text)
        tech_stack = list(dict.fromkeys(tags))[:16]
        source_text = re.sub(r"\s+", " ", markdown_text).strip()
        evidence_map = []
        for item in highlights:
            compact = item[:120]
            quote = compact if compact in source_text else source_text[:120]
            evidence_map.append({"claim": item, "source_quote": quote, "confidence": 0.98 if compact in source_text else 0.7})
        content = {
            "summary": summary[:260],
            "role": role[:128],
            "tech_stack": tech_stack,
            "highlights": highlights,
            "evidence_map": evidence_map,
        }
        return {"fact_type": "project", "title": title[:255], "content": content, "tags": ["项目经历"], "evidence": markdown_text[:10000], "is_verified": False}

    @staticmethod
    def _align_evidence_map(
        highlights: list[str],
        markdown_text: str,
        model_evidence: Any,
    ) -> list[dict[str, Any]]:
        """Attach compact source quotes locally so evidence does not consume LLM output tokens."""
        source_text = re.sub(r"\s+", " ", markdown_text).strip()
        source_candidates = [
            re.sub(r"\s+", " ", line).strip()
            for line in markdown_text.splitlines()
            if line.strip() and not re.match(r"^#{1,6}\s+", line.strip())
        ]
        source_candidates = [candidate[:160] for candidate in source_candidates]
        model_items = model_evidence if isinstance(model_evidence, list) else []

        def tokens(value: str) -> set[str]:
            return set(re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9+#.-]{1,}", value.lower()))

        normalized: list[dict[str, Any]] = []
        for index, highlight in enumerate(highlights):
            claim = str(highlight).strip()
            if not claim:
                continue
            source_quote = ""
            confidence = 0.0
            if index < len(model_items) and isinstance(model_items[index], dict):
                candidate_quote = re.sub(r"\s+", " ", str(model_items[index].get("source_quote") or "")).strip()
                if candidate_quote and candidate_quote in source_text:
                    source_quote = candidate_quote[:120]
                    try:
                        confidence = float(model_items[index].get("confidence") or 0.8)
                    except (TypeError, ValueError):
                        confidence = 0.8
            if not source_quote and claim in source_text:
                source_quote = claim[:120]
                confidence = 0.98
            if not source_quote and source_candidates:
                claim_tokens = tokens(claim)
                scored = sorted(
                    ((len(claim_tokens & tokens(candidate)), candidate) for candidate in source_candidates),
                    key=lambda item: item[0],
                    reverse=True,
                )
                score, best = scored[0]
                if score:
                    source_quote = best[:120]
                    confidence = min(0.95, 0.55 + score * 0.08)
            if not source_quote:
                source_quote = source_text[:120]
                confidence = 0.35
            normalized.append({"claim": claim, "source_quote": source_quote, "confidence": round(max(0.0, min(1.0, confidence)), 2)})
        return normalized

    @staticmethod
    def _prepare_markdown_for_extraction(markdown_text: str, max_chars: int = 24000) -> str:
        normalized = "\n".join(line.rstrip() for line in markdown_text.replace("\x00", "").splitlines()).strip()
        if len(normalized) <= max_chars:
            return normalized
        logger.warning("Markdown fact extraction input truncated from %s to %s chars", len(normalized), max_chars)
        return normalized[:max_chars] + "\n\n[原文超出输入上限，以上内容为可处理范围；不得推断截断部分。]"

    async def normalize_job(self, raw_content: str, source_url: str | None) -> dict[str, Any]:
        cached = self._read_normalized_cache(raw_content, source_url)
        if cached:
            logger.info("Career job normalization cache hit")
            return cached

        started_at = perf_counter()
        normalized_content = raw_content.strip()[:12000]
        prompt = f"""Convert this job description into JSON only. Use this shape:
{{"title":"","company":"","location":"","employment_type":"","seniority":"","responsibilities":[""],"required_skills":[""],"preferred_skills":[""],"education_requirements":[""],"language_requirements":[""],"keywords":[""],"summary":""}}.
Separate strict requirements from preferred qualifications. Use empty strings or arrays where information is absent. Do not infer unsupported facts.
SOURCE URL: {source_url or "not provided"}
JOB DESCRIPTION:
{normalized_content}"""
        result = await self._invoke_json(prompt)
        normalized = {
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
        self._write_normalized_cache(raw_content, source_url, normalized)
        logger.info(
            "Career job normalization completed in %.0fms input_chars=%s",
            (perf_counter() - started_at) * 1000,
            len(normalized_content),
        )
        return normalized

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
For 实习经历 and 项目经历, always use entries and follow this display structure: title/company on the left, role/degree in the middle, period on the right, then a 项目简介 or 个人职责与成果, 技术栈, and detailed 技术亮点/核心成果. Prefer fact.content.role and fact.content.tech_stack when present. Use each fact.content.highlights as separate, evidence-grounded bullets; preserve the technical method and result instead of rewriting them as generic claims. Do not leave fields blank if the supplied fact explicitly contains the value; do not infer a missing value. Do not put an entire experience into one bullet.
Order internship and project entries by relevance to the target role, then recency. Tailoring may reorder and emphasize evidence, but must not delete substantive source details from any selected experience. For 竞赛与荣誉, select at most five high-value, evidenced items; order international/national awards before provincial awards, then scholarships and other honors. Make the headline a concise target role, and keep every bullet specific to the target job.
JOB:
{json.dumps(job, ensure_ascii=False)}
VERIFIED FACTS:
{json.dumps(facts, ensure_ascii=False)}"""
        try:
            return await self._invoke_json(prompt, llm=self._resume_llm)
        except ValueError as exc:
            logger.warning(
                "Tailored resume generation fell back to deterministic assembly model=%s error=%s",
                self._model,
                exc,
            )
            return self._fallback_tailored_resume(job, facts)

    @staticmethod
    def _fallback_tailored_resume(job: dict[str, Any], facts: list[dict[str, Any]]) -> dict[str, Any]:
        """Keep generation usable when the model returns truncated or invalid JSON."""
        sections: list[dict[str, Any]] = []
        experience_entries: list[dict[str, Any]] = []
        project_entries: list[dict[str, Any]] = []
        skill_items: list[dict[str, Any]] = []
        award_items: list[dict[str, Any]] = []
        skills: list[str] = []

        for fact in facts:
            fact_id = fact.get("id")
            content = fact.get("content") if isinstance(fact.get("content"), dict) else {}
            highlights = [str(item).strip() for item in content.get("highlights", []) if str(item).strip()]
            tech_stack = [str(item).strip() for item in content.get("tech_stack", []) if str(item).strip()]
            skills.extend(tech_stack)
            fact_type = str(fact.get("fact_type") or "")
            if fact_type in {"experience", "project"}:
                entry = {
                    "fact_ids": [fact_id],
                    "title": str(fact.get("title") or ""),
                    "subtitle": str(content.get("role") or ""),
                    "period": str(content.get("period") or ""),
                    "summary": str(content.get("summary") or ""),
                    "tech_stack": tech_stack,
                    "items": [
                        {"fact_ids": [fact_id], "label": "", "text": highlight}
                        for highlight in highlights
                    ],
                }
                if fact_type == "experience":
                    experience_entries.append(entry)
                else:
                    project_entries.append(entry)
            elif fact_type == "skill":
                text = str(content.get("summary") or fact.get("title") or "").strip()
                if text:
                    skill_items.append({"fact_ids": [fact_id], "label": str(fact.get("title") or ""), "text": text})
            elif fact_type in {"award", "certificate"}:
                award_items.append({
                    "fact_ids": [fact_id],
                    "label": str(fact.get("title") or ""),
                    "text": str(content.get("summary") or fact.get("evidence") or ""),
                })

        if experience_entries:
            sections.append({"heading": "实习经历", "entries": experience_entries})
        if project_entries:
            sections.append({"heading": "项目经历", "entries": project_entries})
        if skill_items:
            sections.append({"heading": "专业技能", "items": skill_items})
        if award_items:
            sections.append({"heading": "竞赛与荣誉", "items": award_items[:5]})
        return {
            "headline": str(job.get("title") or "求职者"),
            "summary": str(job.get("summary") or ""),
            "sections": sections,
            "skills": list(dict.fromkeys(skills)),
            "match_analysis": {
                "matched_requirements": [],
                "gaps": list(job.get("required_skills") or []),
                "selected_fact_ids": [fact.get("id") for fact in facts if fact.get("id") is not None],
            },
        }

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

    async def _invoke_json(self, prompt: str, llm: ChatOpenAI | None = None) -> dict[str, Any]:
        client = llm or self._llm
        try:
            response = await client.ainvoke([HumanMessage(content=prompt)])
        except Exception as exc:
            if "not available in your region" in str(exc).lower() and self._model != "openrouter/auto":
                try:
                    fallback = ChatOpenAI(
                        model="openrouter/auto",
                        temperature=0,
                        max_tokens=max(
                            settings.CAREER_RESUME_MAX_TOKENS if client is self._resume_llm else settings.CAREER_LLM_MAX_TOKENS,
                            1600,
                        ),
                        timeout=settings.CAREER_RESUME_TIMEOUT if client is self._resume_llm else settings.CAREER_LLM_TIMEOUT,
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
        logger.warning(
            "AI JSON parsing failed response_chars=%s response_tail=%r",
            len(cleaned),
            cleaned[-180:],
        )
        raise ValueError("The AI response was not valid JSON. Please retry.")

    @staticmethod
    def _string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()][:50]
