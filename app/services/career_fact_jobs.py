import asyncio
from typing import Any

from app.schemas.career import CareerFactCreate
from app.services.career_studio import CareerStudioService
from app.services.career_knowledge import normalize_project_claims


def _apply_project_metadata(fact: dict[str, Any], metadata: dict[str, Any], source_document: dict[str, Any]) -> dict[str, Any]:
    """Overlay user-owned project metadata after AI content extraction."""
    normalized = dict(fact)
    project_metadata = metadata if isinstance(metadata, dict) else {}
    content = dict(normalized.get("content") or {}) if isinstance(normalized.get("content"), dict) else {}
    title = str(project_metadata.get("title") or source_document.get("title") or normalized.get("title") or "未命名项目").strip()
    fact_type = project_metadata.get("fact_type") if project_metadata.get("fact_type") in {"experience", "project"} else "project"
    normalized["fact_type"] = fact_type
    normalized["title"] = title[:255]
    for field, max_length in (("period", 128), ("company", 255), ("role", 128)):
        value = str(project_metadata.get(field) or "").strip()
        if value:
            content[field] = value[:max_length]
        else:
            content.pop(field, None)

    if fact_type == "experience":
        # Internship uploads are company-level facts whose extracted content belongs
        # to one nested project, so the editor can save it under project highlights.
        project = {
            "title": title[:255],
            "summary": str(content.get("summary") or "").strip()[:1200],
            "engineering_challenge": str(content.get("engineering_challenge") or "").strip()[:1200],
            "design_rationale": str(content.get("design_rationale") or "").strip()[:1200],
            "industrial_roles": content.get("industrial_roles") if isinstance(content.get("industrial_roles"), list) else [],
            "role_variants": content.get("role_variants") if isinstance(content.get("role_variants"), list) else [],
            "role": str(content.get("role") or "").strip()[:128],
            "tech_stack": [str(item).strip() for item in content.get("tech_stack", []) if str(item).strip()][:16],
            "highlights": [str(item).strip() for item in content.get("highlights", []) if str(item).strip()][:8],
            "evidence_map": content.get("evidence_map") if isinstance(content.get("evidence_map"), list) else [],
            "tags": [str(item).strip() for item in normalized.get("tags", []) if str(item).strip()][:12],
            "evidence": str(normalized.get("evidence") or "").strip()[:10000],
        }
        content["projects"] = [project]
        content["role_variants"] = []
        content["highlights"] = []
        normalized["title"] = str(content.get("company") or title).strip()[:255]
    # The uploader, not the model, is authoritative for the project label.
    content["metadata_source"] = "user_upload"
    content = normalize_project_claims(content, normalized["title"])
    normalized["content"] = content
    return normalized


async def process_career_fact_job(payload: dict[str, Any]) -> dict[str, Any]:
    service = CareerStudioService()
    fact_payload = await service.extract_fact_from_markdown(
        str(payload.get("content_text") or ""),
        str(payload.get("file_name") or "uploaded-document.md"),
        single_project=True,
        project_metadata=payload.get("project_metadata") or payload.get("source_document", {}).get("project_metadata") or {},
        allow_fallback=False,
    )
    warnings = fact_payload.pop("_warnings", []) if isinstance(fact_payload, dict) else []
    quality = fact_payload.pop("_quality", {}) if isinstance(fact_payload, dict) else {}
    raw_facts = fact_payload.pop("facts", None) if isinstance(fact_payload, dict) else None
    source_document = payload.get("source_document") or {}
    project_metadata = payload.get("project_metadata") or source_document.get("project_metadata") or {}
    if isinstance(raw_facts, list):
        raw_facts = [_apply_project_metadata(item, project_metadata, source_document) for item in raw_facts]
        raw_facts = raw_facts[:1]
        facts = [CareerFactCreate.model_validate(item) for item in raw_facts]
    else:
        fact_payload = _apply_project_metadata(fact_payload, project_metadata, source_document)
        facts = [CareerFactCreate.model_validate(fact_payload)]
    return {
        "fact": facts[0].model_dump(mode="json") if len(facts) == 1 else None,
        "facts": [item.model_dump(mode="json") for item in facts],
        "source_document": source_document,
        "warnings": warnings,
        "quality": quality,
        "status": "fallback" if quality.get("used_fallback") else "draft",
        "message": "已从 Skill 提取项目事实草稿，请核对后保存；保存时会把原文绑定到该项目事实。" if not quality.get("used_fallback") else warnings[0],
    }


def run_career_fact_job(payload: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(process_career_fact_job(payload))
