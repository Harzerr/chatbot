import re
from pathlib import Path
from typing import Any

from app.services.career_resume_domain import _clean_resume_bullet, _is_resume_metadata_text


_PROJECT_BOUNDARY = re.compile(r"(?:项目|系统|平台|服务|模块|工具|引擎|project|system|platform|service|tool)", re.IGNORECASE)
_QUESTION_HEADING = re.compile(r"[?？]|如何|为什么|怎样|怎么|什么")
_CONTEXT_HEADINGS = ("概述", "背景", "简介", "业务", "目标", "overview", "background")
_TECH_HEADINGS = ("技术栈", "技术选型", "依赖", "开发环境", "运行环境", "tech stack", "stack")
_ROLE_HEADINGS = ("角色", "职位", "岗位", "职责", "分工", "role", "responsibility")
_NON_CONTENT_HEADINGS = ("文档目的", "资料来源", "版本", "目录", "附录", "面试", "faq")
_ACTION_PREFIX = re.compile(
    r"^(?:设计|实现|构建|开发|采用|使用|基于|通过|完成|优化|重构|处理|解析|提取|"
    r"搭建|编写|支持|负责|参与|将|从|根据|计算|解决|定位|验证|测试)"
)


def _normalize_heading(value: str) -> str:
    return re.sub(r"[\s:：、.。,，;；()（）]+", "", value).lower()


def _contains_any(value: str, markers: tuple[str, ...]) -> bool:
    normalized = _normalize_heading(value)
    return any(_normalize_heading(marker) in normalized for marker in markers)


def _plain_sentence(value: str) -> str:
    text = _clean_resume_bullet(value).rstrip("；;，,")
    if not text:
        return ""
    return text if text.endswith(("。", "！", "？", ".", "!", "?")) else text + "。"


def _parse_sections(markdown_text: str) -> tuple[str, list[dict[str, Any]]]:
    sections: list[dict[str, Any]] = []
    current = {"level": 0, "heading": "正文", "lines": []}
    document_title = ""
    for raw_line in markdown_text.splitlines():
        line = raw_line.strip()
        heading = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if heading:
            if current["lines"] or current["heading"] != "正文":
                sections.append(current)
            level = len(heading.group(1))
            title = heading.group(2).strip()
            if level == 1 and not document_title:
                document_title = title
            current = {"level": level, "heading": title, "lines": []}
            continue
        if line:
            current["lines"].append(raw_line.rstrip())
    if current["lines"] or current["heading"] != "正文":
        sections.append(current)
    return document_title, sections


def _project_groups(sections: list[dict[str, Any]]) -> list[tuple[str, list[dict[str, Any]]]]:
    boundaries = [
        index
        for index, section in enumerate(sections)
        if section["level"] >= 2
        and _PROJECT_BOUNDARY.search(section["heading"])
        and not _QUESTION_HEADING.search(section["heading"])
        and not _contains_any(section["heading"], _CONTEXT_HEADINGS + _TECH_HEADINGS + _ROLE_HEADINGS + _NON_CONTENT_HEADINGS)
    ]
    if len(boundaries) < 2:
        return []

    groups: list[tuple[str, list[dict[str, Any]]]] = []
    for position, start in enumerate(boundaries):
        level = sections[start]["level"]
        end = len(sections)
        for candidate in boundaries[position + 1:]:
            if sections[candidate]["level"] <= level:
                end = candidate
                break
        groups.append((sections[start]["heading"], sections[start:end]))
    return groups


def _extract_tech_stack(sections: list[dict[str, Any]]) -> list[str]:
    values: list[str] = []
    for section in sections:
        if not _contains_any(section["heading"], _TECH_HEADINGS):
            continue
        for line in section["lines"]:
            line = re.sub(r"^(?:技术栈|技术选型|主要技术|依赖)\s*[:：]", "", line, flags=re.IGNORECASE)
            for value in re.split(r"[,，、;；|/]+", line):
                cleaned = value.strip(" `*-•")
                if cleaned and not _is_resume_metadata_text(cleaned):
                    values.append(cleaned)
    return list(dict.fromkeys(values))[:16]


def _extract_role(sections: list[dict[str, Any]]) -> str:
    for section in sections:
        if _contains_any(section["heading"], _ROLE_HEADINGS):
            for line in section["lines"]:
                cleaned = _plain_sentence(line)
                if cleaned:
                    return cleaned[:128]
    return ""


def _extract_content(sections: list[dict[str, Any]]) -> tuple[str, list[str], list[dict[str, Any]], str]:
    summary_lines: list[str] = []
    highlights: list[str] = []
    evidence_map: list[dict[str, Any]] = []
    evidence_lines: list[str] = []

    for section in sections:
        heading = section["heading"]
        if _contains_any(heading, _TECH_HEADINGS + _ROLE_HEADINGS + _NON_CONTENT_HEADINGS):
            continue
        is_context = _contains_any(heading, _CONTEXT_HEADINGS)
        is_question = bool(_QUESTION_HEADING.search(heading))
        for raw_line in section["lines"]:
            if _is_resume_metadata_text(raw_line):
                continue
            stripped_line = raw_line.strip()
            evidence_lines.append(stripped_line)
            bullet = re.match(r"^(?:[-*+•]|\d+[.)])\s+(.+)$", stripped_line)
            source = bullet.group(1) if bullet else stripped_line
            cleaned = _plain_sentence(source)
            if not cleaned:
                continue
            if is_context and not bullet:
                summary_lines.append(cleaned)
                continue
            if is_question and not bullet and not _ACTION_PREFIX.match(cleaned):
                continue
            if raw_line != raw_line.lstrip() and highlights and not bullet:
                highlights[-1] = highlights[-1].rstrip("。") + "；" + cleaned
                evidence_map[-1]["claim"] = highlights[-1]
                evidence_map[-1]["source_quote"] = (evidence_map[-1]["source_quote"] + " " + source)[:240]
            elif bullet or _ACTION_PREFIX.match(cleaned):
                if cleaned not in highlights:
                    highlights.append(cleaned)
                    evidence_map.append({"claim": cleaned, "source_quote": source[:240], "confidence": 1.0})
            elif not summary_lines:
                summary_lines.append(cleaned)

    summary = "".join(summary_lines[:2])[:260]
    return summary, highlights[:8], evidence_map[:8], "\n".join(evidence_lines)[:10000]


def parse_markdown_project_facts(markdown_text: str, file_name: str) -> list[dict[str, Any]]:
    """Create a conservative fallback from Markdown structure only.

    This parser intentionally knows nothing about a particular company, project,
    technology, or target role. Uploaded documents normally use the Skill path;
    this fallback exists for explicit legacy callers and offline recovery.
    """
    document_title, sections = _parse_sections(markdown_text)
    default_title = document_title or Path(file_name).stem or "未命名项目"
    groups = _project_groups(sections) or [(default_title, sections)]
    facts: list[dict[str, Any]] = []
    for title, project_sections in groups:
        summary, highlights, evidence_map, evidence = _extract_content(project_sections)
        if not summary and not highlights:
            continue
        facts.append({
            "fact_type": "project",
            "title": re.sub(r"^\s*\d+(?:\.\d+)*[.、:)）\s]+", "", title).strip()[:255] or default_title,
            "content": {
                "summary": summary,
                "engineering_challenge": "",
                "design_rationale": "",
                "industrial_roles": [],
                "role_variants": [],
                "role": _extract_role(project_sections),
                "tech_stack": _extract_tech_stack(project_sections),
                "highlights": highlights,
                "evidence_map": evidence_map,
            },
            "tags": ["项目经历"],
            "evidence": evidence or markdown_text[:10000],
            "is_verified": False,
        })
    return facts
