import asyncio
from typing import Any

from app.schemas.career import CareerFactCreate
from app.services.career_studio import CareerStudioService


async def process_career_fact_job(payload: dict[str, Any]) -> dict[str, Any]:
    service = CareerStudioService()
    fact_payload = await service.extract_fact_from_markdown(
        str(payload.get("content_text") or ""),
        str(payload.get("file_name") or "uploaded-document.md"),
    )
    warnings = fact_payload.pop("_warnings", []) if isinstance(fact_payload, dict) else []
    quality = fact_payload.pop("_quality", {}) if isinstance(fact_payload, dict) else {}
    fact = CareerFactCreate.model_validate(fact_payload)
    return {
        "fact": fact.model_dump(mode="json"),
        "source_document": payload.get("source_document") or {},
        "warnings": warnings,
        "quality": quality,
        "status": "fallback" if warnings else "draft",
        "message": "已从 Markdown 提取项目事实草稿，请核对后保存；保存时会把原文绑定到该项目事实。" if not warnings else warnings[0],
    }


def run_career_fact_job(payload: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(process_career_fact_job(payload))
