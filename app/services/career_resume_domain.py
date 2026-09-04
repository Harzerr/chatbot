import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

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


_ROLE_TAXONOMY_PATH = Path(__file__).with_name("career_role_taxonomy.json")


@lru_cache(maxsize=1)
def _role_taxonomy() -> tuple[dict[str, Any], ...]:
    """Load the versioned role taxonomy without coupling code to project names."""
    try:
        payload = json.loads(_ROLE_TAXONOMY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return ()
    roles = payload.get("roles") if isinstance(payload, dict) else []
    return tuple(item for item in roles if isinstance(item, dict) and item.get("role"))


_RESUME_METADATA_LABELS = (
    "实习时间",
    "任职时间",
    "工作时间",
    "技术方向",
    "主要技术",
    "技术栈",
    "技术选型",
    "开发环境",
    "运行环境",
    "项目角色",
    "角色",
    "职位",
    "岗位",
    "公司",
    "部门",
    "工作地点",
    "实习地点",
    "覆盖项目",
    "文档版本",
    "生成日期",
    "生成时间",
    "更新时间",
    "文档作者",
    "资料来源",
)
_TABLE_HEADER_LABELS = {"目标", "说明", "模块", "功能", "项目", "类别", "内容", "指标", "结果"}


def _markdown_table_cells(value: Any) -> list[str]:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if "|" not in text:
        return []
    cells = [cell.strip() for cell in text.strip("|").split("|")]
    return [cell for cell in cells if cell]


def _is_resume_metadata_text(value: Any) -> bool:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return True
    if re.match(r"^(?:>\s*|[-*•]\s*|\d+[.)]\s*)+", text):
        text = re.sub(r"^(?:>\s*|[-*•]\s*|\d+[.)]\s*)+", "", text).strip()
    if re.match(
        rf"^(?:{'|'.join(map(re.escape, _RESUME_METADATA_LABELS))})\s*[:：]",
        text,
        flags=re.IGNORECASE,
    ):
        return True
    if re.fullmatch(r"20\d{2}[./-]\d{1,2}\s*[—–~～-]\s*(?:20\d{2}[./-])?\d{1,2}", text):
        return True
    cells = _markdown_table_cells(text)
    if len(cells) >= 2:
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            return True
        if len(cells) == 2 and cells[0] in _TABLE_HEADER_LABELS and cells[1] in _TABLE_HEADER_LABELS:
            return True
    return bool(re.match(r"^(?:工作内容包括|主要工作|职责概述)\s*[:：]?\s*$", text))


def _clean_resume_bullet(value: Any) -> str:
    """Convert Markdown fragments into a plain resume bullet or drop document noise."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"^(?:>\s*|[-*•]\s*|\d+[.)]\s*)+", "", text).strip()
    if _is_resume_metadata_text(text):
        return ""
    cells = _markdown_table_cells(text)
    if len(cells) >= 2:
        detail = "；".join(cells[1:])
        # Resume bullets should carry the implementation statement, not a
        # table's category label, which is often a document-only heading.
        text = detail or cells[0]
    text = re.sub(r"^\|+|\|+$", "", text).strip()
    return "" if _is_resume_metadata_text(text) else text


def _clean_variant_text(value: Any) -> str:
    """Remove extraction artifacts without changing the factual claim."""
    text = _clean_resume_bullet(value)
    text = re.sub(r"^(?:实现|完成)\s*[>:：]\s*", "", text)
    text = re.sub(r"^(?:围绕[^，,。；;]+[，,]\s*)+", "", text)
    text = re.sub(r"^(?:从[^，,。；;]+视角看?[，,]\s*)", "", text)
    text = text.rstrip("；;，,")
    text = re.sub(r"；。$", "。", text)
    return text


def _polish_variant_item(title: str, item: str) -> str:
    """Normalize punctuation without inventing actions or technology semantics."""
    text = _clean_variant_text(item)
    if not text:
        return ""
    text = re.sub(r"\s+([，。；：])", r"\1", text)
    return text if text.endswith(("。", "！", "？", ".", "!", "?")) else text + "。"


def _resume_ready_highlights(title: str, role: str, highlights: list[str]) -> list[str]:
    """Preserve evidence wording; role-specific rewriting belongs to the Skill."""
    result = [_polish_variant_item(title, raw) for raw in highlights]
    return list(dict.fromkeys(item for item in result if item))[:8]


def _polish_variant_summary(title: str, summary: str) -> str:
    return _clean_variant_text(summary)


def _normalize_industrial_roles(value: Any) -> list[dict[str, Any]]:
    """Normalize inferred job tracks without treating them as verified job titles."""
    if not isinstance(value, list):
        return []
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, str):
            role = item.strip()
            item = {"role": role}
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or item.get("title") or "").strip()[:120]
        if not role or role in seen:
            continue
        evidence = item.get("evidence") if isinstance(item.get("evidence"), list) else []
        try:
            confidence = float(item.get("confidence") or 0.0)
        except (TypeError, ValueError):
            confidence = 0.0
        normalized.append({
            "role": role,
            "fit_reason": str(item.get("fit_reason") or item.get("reason") or "").strip()[:500],
            "evidence": [str(entry).strip()[:80] for entry in evidence if str(entry).strip()][:8],
            "confidence": round(max(0.0, min(1.0, confidence)), 2),
        })
        seen.add(role)
    return normalized[:4]


def _role_marker_present(source: str, marker: str) -> bool:
    normalized_marker = marker.strip().lower()
    if not normalized_marker:
        return False
    if re.search(r"[\u4e00-\u9fff]", normalized_marker):
        return normalized_marker in source
    return bool(re.search(
        rf"(?<![a-z0-9]){re.escape(normalized_marker)}(?![a-z0-9])",
        source,
        flags=re.IGNORECASE,
    ))


def infer_industrial_roles(title: str, content: dict[str, Any] | None = None, evidence: str = "") -> list[dict[str, Any]]:
    """Infer likely enterprise role tracks from concrete project evidence."""
    content = content if isinstance(content, dict) else {}
    source = " ".join([
        title,
        str(content.get("summary") or ""),
        str(content.get("engineering_challenge") or ""),
        str(content.get("design_rationale") or ""),
        " ".join(str(item) for item in content.get("tech_stack", []) if str(item).strip()),
        " ".join(str(item) for item in content.get("highlights", []) if str(item).strip()),
        evidence,
    ])
    normalized_source = source.lower()
    tracks: list[dict[str, Any]] = []
    for rule in _role_taxonomy():
        markers = [str(marker) for marker in rule.get("markers", []) if str(marker).strip()]
        strong_markers = [str(marker) for marker in rule.get("strong_markers", []) if str(marker).strip()]
        matched = [marker for marker in markers if _role_marker_present(normalized_source, marker)]
        strong_matched = [marker for marker in strong_markers if _role_marker_present(normalized_source, marker)]
        min_matches = max(1, int(rule.get("min_matches") or 2))
        if len(matched) < min_matches or not strong_matched:
            continue
        confidence = min(0.9, 0.5 + len(matched) * 0.06)
        tracks.append({
            "role": rule["role"],
            "fit_reason": f"项目证据包含{'、'.join(matched[:4])}，与{rule.get('focus', '该岗位核心职责')}存在直接交集。",
            "evidence": matched[:8],
            "confidence": round(confidence, 2),
        })
    tracks.sort(key=lambda item: item["confidence"], reverse=True)
    return tracks[:3]


def _normalize_role_variants(value: Any, title: str = "") -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    variants: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        role = str(item.get("role") or "").strip()[:120]
        if not role or role in seen:
            continue
        highlights = [
            _polish_variant_item(title, str(entry))
            for entry in item.get("highlights", [])
            if str(entry).strip()
        ]
        highlights = [entry for entry in highlights if entry]
        raw_summary = str(item.get("summary") or "").strip()
        variants.append({
            "role": role,
            "focus": str(item.get("focus") or "").strip()[:240],
            "summary": (_polish_variant_summary(title, raw_summary) if title else _clean_variant_text(raw_summary))[:1200],
            "engineering_challenge": str(item.get("engineering_challenge") or "").strip()[:1200],
            "design_rationale": str(item.get("design_rationale") or "").strip()[:1200],
            "highlights": highlights[:8],
            "evidence_map": item.get("evidence_map") if isinstance(item.get("evidence_map"), list) else [],
        })
        seen.add(role)
    return variants[:3]


def build_role_variants(
    title: str,
    content: dict[str, Any] | None = None,
    evidence: str = "",
) -> list[dict[str, Any]]:
    """Build conservative role-specific drafts when the model omits variants."""
    content = content if isinstance(content, dict) else {}
    tracks = _normalize_industrial_roles(content.get("industrial_roles")) or infer_industrial_roles(title, content, evidence)
    summary = str(content.get("summary") or "").strip()
    challenge = str(content.get("engineering_challenge") or "").strip()
    rationale = str(content.get("design_rationale") or "").strip()
    highlights = [str(item).strip() for item in content.get("highlights", []) if str(item).strip()]
    variants: list[dict[str, Any]] = []
    for track in tracks:
        role = str(track.get("role") or "").strip()
        focus = next((str(item.get("focus") or "") for item in _role_taxonomy() if item.get("role") == role), "")
        role_highlights = _resume_ready_highlights(title, role, highlights)
        role_summary = _polish_variant_summary(title, summary)
        variants.append({
            "role": role,
            "focus": focus,
            "summary": role_summary[:1200],
            "engineering_challenge": challenge,
            "design_rationale": rationale,
            "highlights": role_highlights[:8],
            "evidence_map": [],
        })
    return variants[:3]


def sanitize_resume_content(content: Any, title: str = "", fact_type: str = "") -> dict[str, Any]:
    """Remove Markdown/document noise from stored content before display or generation."""
    if not isinstance(content, dict):
        return {}
    normalized = dict(content)

    def clean_highlights(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return list(dict.fromkeys(
            cleaned
            for item in value
            for cleaned in [_polish_variant_item(title, item)]
            if cleaned
        ))[:8]

    normalized["highlights"] = clean_highlights(normalized.get("highlights"))
    legacy_experience = (
        fact_type == "experience"
        and normalized.get("metadata_source") == "user_upload"
        and not normalized.get("projects")
        and normalized["highlights"]
    )
    variants: list[dict[str, Any]] = []
    for item in normalized.get("role_variants", []) if isinstance(normalized.get("role_variants"), list) else []:
        if not isinstance(item, dict):
            continue
        variant = dict(item)
        variant["highlights"] = clean_highlights(item.get("highlights"))
        variants.append(variant)
    normalized["role_variants"] = variants

    if legacy_experience:
        normalized["projects"] = [{
            "title": title[:255] or "未命名项目",
            "summary": str(normalized.get("summary") or "").strip(),
            "engineering_challenge": str(normalized.get("engineering_challenge") or "").strip(),
            "design_rationale": str(normalized.get("design_rationale") or "").strip(),
            "industrial_roles": normalized.get("industrial_roles") if isinstance(normalized.get("industrial_roles"), list) else [],
            "role_variants": variants,
            "role": str(normalized.get("role") or "").strip(),
            "tech_stack": list(normalized.get("tech_stack") or []) if isinstance(normalized.get("tech_stack"), list) else [],
            "highlights": normalized["highlights"],
            "evidence_map": normalized.get("evidence_map") if isinstance(normalized.get("evidence_map"), list) else [],
            "tags": [],
            "evidence": "",
        }]
        normalized["highlights"] = []
        normalized["role_variants"] = []

    projects: list[dict[str, Any]] = []
    for item in normalized.get("projects", []) if isinstance(normalized.get("projects"), list) else []:
        if not isinstance(item, dict):
            continue
        project = dict(item)
        project["highlights"] = clean_highlights(item.get("highlights"))
        project_variants: list[dict[str, Any]] = []
        for variant_item in item.get("role_variants", []) if isinstance(item.get("role_variants"), list) else []:
            if not isinstance(variant_item, dict):
                continue
            project_variant = dict(variant_item)
            project_variant["highlights"] = clean_highlights(variant_item.get("highlights"))
            project_variants.append(project_variant)
        project["role_variants"] = project_variants
        projects.append(project)
    if isinstance(normalized.get("projects"), list):
        normalized["projects"] = projects

    for field in ("summary", "engineering_challenge", "design_rationale"):
        if _is_resume_metadata_text(normalized.get(field)):
            normalized[field] = ""
    return normalized


def select_role_variant(job: dict[str, Any] | None, content: dict[str, Any] | None) -> dict[str, Any]:
    """Select the role-specific project draft that best overlaps with a JD."""
    content = content if isinstance(content, dict) else {}
    variants = _normalize_role_variants(content.get("role_variants"))
    if not variants:
        return {}
    job = job if isinstance(job, dict) else {}
    job_text = json.dumps(job, ensure_ascii=False).lower()
    requirements = [
        str(item).strip().lower()
        for key in ("required_skills", "preferred_skills", "responsibilities")
        for item in (job.get(key) or [])
        if str(item).strip()
    ]
    if not requirements:
        return variants[0]

    def tokens(value: str) -> set[str]:
        return set(re.findall(r"[\u4e00-\u9fff]{2,}|[a-z][a-z0-9+#./_-]{1,}", value.lower()))

    job_tokens = tokens(job_text)
    scored: list[tuple[int, dict[str, Any]]] = []
    for variant in variants:
        variant_text = json.dumps(variant, ensure_ascii=False).lower()
        variant_tokens = tokens(variant_text)
        score = len(job_tokens & variant_tokens)
        score += sum(2 for requirement in requirements if requirement in variant_text)
        scored.append((score, variant))
    scored.sort(key=lambda item: item[0], reverse=True)
    return scored[0][1]
