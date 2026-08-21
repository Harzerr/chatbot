import asyncio
import json
import re
from pathlib import Path
from time import perf_counter
from typing import Annotated, Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.career import CareerFact, CareerKnowledgeChunk, CareerKnowledgeDocument, JobPosting, ResumeDocument
from app.models.user import User
from app.schemas.career import (
    CareerFactCreate,
    CareerFactRead,
    CareerFactUpdate,
    CareerKnowledgeDocumentRead,
    CareerKnowledgeDocumentUpdate,
    FactExtractionResponse,
    FactExtractionWarning,
    MarkdownFactExtractionResponse,
    JobImportRequest,
    JobPostingRead,
    JobPostingUpdate,
    ResumeDocumentRead,
    ResumeDocumentUpdate,
    ResumeProfileImportRequest,
    ResumeProfileImportResponse,
    TailoredResumeRequest,
)
from app.services.career_studio import CareerStudioService, infer_industrial_roles, sanitize_resume_content, select_role_variant
from app.services.task_queue import (
    QueueUnavailable,
    enqueue_career_evidence_index_job,
    enqueue_career_fact_job,
    get_career_fact_job,
)
from app.utils.logger import setup_logger
from app.services.resume_tex_renderer import build_tex_bundle, compile_resume_pdf
from app.services.career_knowledge import (
    CLAIM_LINKING_VERSION,
    build_knowledge_document_chunks,
    edited_source_hash,
    link_claims_to_chunks,
    normalize_project_claims,
    parse_document,
    project_claims_for_document,
    stable_project_key,
)
from app.core.config import settings

router = APIRouter()
career_studio = CareerStudioService()
logger = setup_logger(__name__)


def _normalize_project_upload_metadata(value: Any, file_name: str) -> dict[str, str]:
    """Keep user-entered project metadata separate from AI-extracted content."""
    item = value if isinstance(value, dict) else {}
    fallback_title = Path(file_name).stem[:255] or "未命名项目"
    fact_type = str(item.get("fact_type") or "project").strip()
    return {
        "title": str(item.get("title") or fallback_title).strip()[:255],
        "period": str(item.get("period") or "").strip()[:128],
        "company": str(item.get("company") or "").strip()[:255],
        "role": str(item.get("role") or "").strip()[:128],
        "fact_type": fact_type if fact_type in {"experience", "project"} else "project",
        "project_key": stable_project_key(str(item.get("title") or fallback_title).strip()),
    }


async def _enqueue_career_evidence_index(document_id: int, user: User) -> None:
    if not getattr(settings, "CAREER_EVIDENCE_VECTOR_ENABLED", False):
        return
    try:
        job = await asyncio.to_thread(
            enqueue_career_evidence_index_job,
            {
                "document_id": document_id,
                "user_id": user.id,
                "tenant_id": user.tenant_id,
            },
        )
        logger.info("Career evidence index queued: document_id=%s job_id=%s", document_id, job.id)
    except QueueUnavailable as exc:
        logger.warning("Career evidence index queue unavailable; lexical retrieval remains active: %s", exc)


async def _replace_knowledge_document_chunks(
    db: AsyncSession,
    document: CareerKnowledgeDocument,
    fact: CareerFact | None = None,
) -> int:
    """Persist the exact chunks later used by lexical and vector retrieval."""
    if fact is None and document.fact_id:
        fact = await db.scalar(
            select(CareerFact).where(
                CareerFact.id == document.fact_id,
                CareerFact.user_id == document.user_id,
            )
        )
    metadata = _json_load(document.metadata_json, {})
    project_key = str(metadata.get("project_key") or "").strip()
    metadata["claim_linking_version"] = CLAIM_LINKING_VERSION
    document.metadata_json = json.dumps(metadata, ensure_ascii=False)
    claims = project_claims_for_document(
        _json_load(fact.content_json, {}) if fact else {},
        fact.title if fact else document.title,
        project_key or None,
    )
    chunks = link_claims_to_chunks(build_knowledge_document_chunks(
        document,
        max_chunk_chars=settings.EVIDENCE_CHUNK_MAX_CHARS,
        overlap_chars=settings.EVIDENCE_CHUNK_OVERLAP_CHARS,
    ), claims)
    await db.execute(
        delete(CareerKnowledgeChunk).where(CareerKnowledgeChunk.document_id == document.id)
    )
    db.add_all(
        [
            CareerKnowledgeChunk(
                document_id=document.id,
                user_id=document.user_id,
                fact_id=document.fact_id,
                chunk_index=chunk["chunk_index"],
                chunk_id=str(chunk["chunk_id"]),
                section=str(chunk["section"])[:255],
                text=str(chunk["text"]),
                project_key=str(chunk.get("project_key") or project_key)[:128],
                claim_ids_json=json.dumps(chunk.get("claim_ids", []), ensure_ascii=False),
                claim_texts_json=json.dumps(chunk.get("claim_texts", []), ensure_ascii=False),
                source_version=chunk.get("source_version"),
                chunking_version=str(chunk["chunking_version"]),
            )
            for chunk in chunks
        ]
    )
    return len(chunks)


def _json_load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _filename_part(value: Any, fallback: str) -> str:
    text = re.sub(r"[\\/:*?\"<>|]+", "-", str(value or "")).strip(" .-")
    return text or fallback


def _fact_response(fact: CareerFact) -> CareerFactRead:
    return CareerFactRead(
        id=fact.id,
        fact_type=fact.fact_type,
        title=fact.title,
        content=sanitize_resume_content(_json_load(fact.content_json, {}), fact.title, fact.fact_type),
        tags=_json_load(fact.tags_json, []),
        evidence=fact.evidence,
        is_verified=fact.is_verified,
        is_archived=fact.is_archived,
        source_resume_name=fact.source_resume_name,
        created_at=fact.created_at,
        updated_at=fact.updated_at,
    )


def _job_response(job: JobPosting) -> JobPostingRead:
    return JobPostingRead(
        id=job.id,
        title=job.title,
        company=job.company,
        source_url=job.source_url,
        raw_content=job.raw_content,
        normalized=_json_load(job.normalized_json, {}),
        extraction_status=job.extraction_status,
        created_at=job.created_at,
        updated_at=job.updated_at,
    )


def _resume_response(document: ResumeDocument) -> ResumeDocumentRead:
    return ResumeDocumentRead(
        id=document.id,
        job_id=document.job_id,
        kind=document.kind,
        title=document.title,
        schema_version=document.schema_version,
        content=_json_load(document.content_json, {}),
        match=_json_load(document.match_json, {}),
        status=document.status,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


def _profile_education(user: User) -> list[dict[str, Any]]:
    try:
        education = json.loads(user.education_json or "[]")
    except (TypeError, json.JSONDecodeError):
        return []
    return education if isinstance(education, list) else []


def _compact_evidence(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip(" \n\t；;")


def _source_highlights(evidence: str, fact_id: int) -> list[dict[str, Any]]:
    source = re.search(r"(?:技术亮点|个人职责与成果)\s*[:：](.*)", evidence, flags=re.DOTALL)
    if not source:
        return []
    highlights: list[dict[str, Any]] = []
    for raw_item in re.findall(r"•\s*(.*?)(?=•|$)", source.group(1), flags=re.DOTALL):
        item = _compact_evidence(raw_item)
        if not item:
            continue
        parts = re.split(r"[：:]", item, maxsplit=1)
        label = parts[0].strip() if len(parts) == 2 else ""
        text = parts[1].strip() if len(parts) == 2 else item
        highlights.append({"fact_ids": [fact_id], "label": label, "text": text})
    return highlights


def _resume_profile_root(draft: dict[str, Any]) -> dict[str, Any]:
    if isinstance(draft.get("profiles"), dict):
        active_name = draft.get("activeName")
        profiles = draft["profiles"]
        if active_name in profiles and isinstance(profiles[active_name], dict):
            return profiles[active_name]
        first_profile = next((value for value in profiles.values() if isinstance(value, dict)), None)
        if first_profile:
            return first_profile
    return draft


def _profile_section(root: dict[str, Any], name: str) -> list[Any]:
    source = root.get("sourceResume") if isinstance(root.get("sourceResume"), dict) else root
    values = source.get(name)
    if isinstance(values, list):
        return values
    parsed = root.get("parsed")
    if isinstance(parsed, dict) and isinstance(parsed.get("sections"), dict):
        parsed_values = parsed["sections"].get(name)
        if isinstance(parsed_values, list):
            return parsed_values
    return []


def _profile_personal(root: dict[str, Any]) -> dict[str, Any]:
    source = root.get("sourceResume") if isinstance(root.get("sourceResume"), dict) else root
    personal = source.get("personal")
    return personal if isinstance(personal, dict) else {}


def _profile_value(value: Any, *keys: str) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if candidate is not None and str(candidate).strip():
                return str(candidate).strip()
    return ""


def _profile_entry(entry: Any) -> tuple[str, list[str]]:
    if isinstance(entry, str):
        return entry.strip(), []
    if not isinstance(entry, dict):
        return "", []
    title = _profile_value(entry, "title", "name", "organization", "school", "company")
    date = _profile_value(entry, "date", "period", "startDate", "start_date")
    if entry.get("endDate") and date and entry.get("endDate") not in date:
        date = f"{date} - {entry['endDate']}"
    details = entry.get("details") or entry.get("responsibilities") or entry.get("highlights") or []
    if isinstance(details, str):
        details = [details]
    if not isinstance(details, list):
        details = []
    lines = [str(item).strip() for item in details if str(item).strip()]
    return "｜".join(part for part in (title, _profile_value(entry, "role", "position")) if part), ([date] if date else []) + lines


def _imported_fact_payload(root: dict[str, Any]) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    sections = (
        ("experience", "experience"),
        ("projects", "project"),
        ("campus", "other"),
        ("honors", "award"),
    )
    for section_name, fact_type in sections:
        for entry in _profile_section(root, section_name):
            title, lines = _profile_entry(entry)
            if not title and lines:
                title, lines = lines[0], lines[1:]
            if not title:
                continue
            facts.append({
                "fact_type": fact_type,
                "title": title[:255],
                "content": {"summary": lines[0] if lines else "", "highlights": lines[1:] if lines else []},
                "tags": [],
                "evidence": "\n".join(lines)[:10000] or title,
                "is_verified": False,
            })

    skills = _profile_section(root, "skills")
    for skill in skills:
        text = _profile_value(skill)[:10000]
        if text:
            facts.append({
                "fact_type": "skill",
                "title": text[:255],
                "content": {"summary": text, "highlights": []},
                "tags": [],
                "evidence": text,
                "is_verified": False,
            })
    return facts


def _enrich_entries_from_evidence(
    generated: dict[str, Any],
    facts: list[dict[str, Any]],
    job: dict[str, Any] | None = None,
) -> None:
    """Restore detailed, verified source wording after the model selects and orders facts."""
    sources = {fact["id"]: fact for fact in facts}
    for section in generated.get("sections", []):
        if not isinstance(section, dict) or section.get("heading") not in {"实习经历", "项目经历"}:
            continue
        for entry in section.get("entries", []):
            if not isinstance(entry, dict):
                continue
            fact_ids = entry.get("fact_ids") if isinstance(entry.get("fact_ids"), list) else []
            if len(fact_ids) != 1 or fact_ids[0] not in sources:
                continue
            fact = sources[fact_ids[0]]
            content = fact.get("content") if isinstance(fact.get("content"), dict) else {}
            industrial_roles = content.get("industrial_roles") if isinstance(content.get("industrial_roles"), list) else []
            if not industrial_roles:
                industrial_roles = infer_industrial_roles(
                    str(fact.get("title") or ""),
                    content,
                    str(fact.get("evidence") or ""),
                )
            if industrial_roles and not entry.get("industrial_roles"):
                entry["industrial_roles"] = industrial_roles
            for field in ("engineering_challenge", "design_rationale"):
                source_value = _compact_evidence(str(content.get(field) or ""))
                if source_value and not str(entry.get(field) or "").strip():
                    entry[field] = source_value[:1200]
            selected_variant = select_role_variant(job, content)
            if selected_variant:
                if selected_variant.get("summary"):
                    entry["summary"] = selected_variant["summary"]
                if selected_variant.get("engineering_challenge"):
                    entry["engineering_challenge"] = selected_variant["engineering_challenge"]
                if selected_variant.get("design_rationale"):
                    entry["design_rationale"] = selected_variant["design_rationale"]
                if selected_variant.get("highlights"):
                    entry["items"] = [
                        {
                            "fact_ids": [fact["id"]],
                            "label": "",
                            "text": str(item).strip(),
                        }
                        for item in selected_variant["highlights"]
                        if str(item).strip()
                    ]
            evidence = str(fact.get("evidence") or "")
            if not evidence:
                continue

            tech_stack = re.search(
                r"技术栈\s*[:：]\s*(.*?)(?=(?:技术亮点|个人职责与成果|项目简介)\s*[:：]|•|$)",
                evidence,
                flags=re.DOTALL,
            )
            if tech_stack:
                stack = _compact_evidence(tech_stack.group(1))
                if stack:
                    entry["tech_stack"] = [part.strip() for part in re.split(r"[、,，]", stack) if part.strip()]

            if section.get("heading") == "项目经历":
                summary = re.search(
                    r"项目简介\s*[:：]\s*(.*?)(?=技术栈\s*[:：]|技术亮点\s*[:：]|$)",
                    evidence,
                    flags=re.DOTALL,
                )
                if summary:
                    detailed_summary = _compact_evidence(summary.group(1))
                    if detailed_summary:
                        entry["summary"] = detailed_summary

            highlights = _source_highlights(evidence, fact["id"])
            if highlights:
                entry["items"] = highlights


def _project_title_and_stack(value: str) -> tuple[str, list[str]]:
    text = _compact_evidence(value)
    match = re.match(r"^(.*?)[（(]([^）)]+)[）)]$", text)
    if not match:
        return text, []
    title = match.group(1).strip(" ：:")
    stack = [part.strip() for part in re.split(r"[/、,，;；|]", match.group(2)) if part.strip()]
    return title or text, stack


def _experience_projects(
    fact: dict[str, Any],
    entry: dict[str, Any],
    job: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Convert one internship fact into stable nested project entries."""
    fact_id = fact.get("id")
    content = fact.get("content") if isinstance(fact.get("content"), dict) else {}
    explicit_projects = content.get("projects") if isinstance(content.get("projects"), list) else []
    if explicit_projects:
        candidates: list[Any] = explicit_projects
    else:
        candidates = entry.get("items") if isinstance(entry.get("items"), list) else []
        candidates = [item for item in candidates if isinstance(item, dict) and str(item.get("label") or "").strip()]
        if not candidates:
            candidates = content.get("highlights") if isinstance(content.get("highlights"), list) else []

    projects: list[dict[str, Any]] = []
    for candidate in candidates:
        engineering_challenge = ""
        design_rationale = ""
        industrial_roles: list[dict[str, Any]] = []
        role_variants: list[dict[str, Any]] = []
        selected_variant: dict[str, Any] = {}
        if isinstance(candidate, dict):
            raw_title = str(candidate.get("title") or candidate.get("label") or "").strip()
            summary = _compact_evidence(str(candidate.get("summary") or candidate.get("text") or ""))
            selected_variant = select_role_variant(job, candidate)
            if selected_variant:
                summary = _compact_evidence(str(selected_variant.get("summary") or summary))
            engineering_challenge = _compact_evidence(str(candidate.get("engineering_challenge") or ""))
            design_rationale = _compact_evidence(str(candidate.get("design_rationale") or ""))
            if selected_variant:
                engineering_challenge = _compact_evidence(str(selected_variant.get("engineering_challenge") or engineering_challenge))
                design_rationale = _compact_evidence(str(selected_variant.get("design_rationale") or design_rationale))
            industrial_roles = candidate.get("industrial_roles") if isinstance(candidate.get("industrial_roles"), list) else []
            role_variants = candidate.get("role_variants") if isinstance(candidate.get("role_variants"), list) else []
            project_items = candidate.get("items") if isinstance(candidate.get("items"), list) else []
            variant_highlights = selected_variant.get("highlights") if isinstance(selected_variant.get("highlights"), list) else []
            candidate_highlights = candidate.get("highlights") if isinstance(candidate.get("highlights"), list) else []
            if not project_items and (variant_highlights or candidate_highlights):
                project_items = [
                    {"text": str(item).strip()}
                    for item in (variant_highlights or candidate_highlights)
                    if str(item).strip()
                ]
            tech_stack = [str(item).strip() for item in candidate.get("tech_stack", []) if str(item).strip()]
        else:
            raw_title = ""
            summary = _compact_evidence(str(candidate))
            project_items = []
            tech_stack = []
            match = re.match(r"^([^：:]{2,80})[：:](.+)$", summary)
            if match:
                raw_title, summary = match.group(1).strip(), match.group(2).strip()

        if not raw_title or not summary:
            if raw_title and project_items:
                first_item = project_items[0]
                if isinstance(first_item, dict):
                    summary = _compact_evidence(str(first_item.get("text") or first_item.get("summary") or ""))
                else:
                    summary = _compact_evidence(str(first_item))
        if not raw_title or not summary:
            continue
        title, parsed_stack = _project_title_and_stack(raw_title)
        if not industrial_roles:
            industrial_roles = infer_industrial_roles(
                title,
                {
                    "summary": summary,
                    "engineering_challenge": engineering_challenge,
                    "design_rationale": design_rationale,
                    "tech_stack": tech_stack or parsed_stack,
                    "highlights": [item.get("text") for item in project_items if isinstance(item, dict)],
                },
                str(fact.get("evidence") or ""),
            )
        projects.append({
            "fact_ids": [fact_id] if fact_id is not None else [],
            "title": title[:255],
            "summary": summary[:1200],
            "engineering_challenge": engineering_challenge[:1200],
            "design_rationale": design_rationale[:1200],
            "industrial_roles": industrial_roles[:4],
            "role_variants": role_variants[:3],
            "tech_stack": (tech_stack or parsed_stack)[:16],
            "items": [
                {
                    "fact_ids": [fact_id] if fact_id is not None else [],
                    "label": str(item.get("label") or ""),
                    "text": str(item.get("text") or item.get("summary") or "").strip(),
                }
                for item in project_items
                if isinstance(item, dict) and str(item.get("text") or item.get("summary") or "").strip()
            ],
        })

    unique: list[dict[str, Any]] = []
    seen: set[str] = set()
    for project in projects:
        key = re.sub(r"\s+", "", project["title"]).lower()
        if key and key not in seen:
            seen.add(key)
            unique.append(project)
    return unique


def _expand_experience_entries(
    generated: dict[str, Any],
    facts: list[dict[str, Any]],
    job: dict[str, Any] | None = None,
) -> None:
    """Guarantee that multi-project internships are not flattened into bullets."""
    sources = {fact["id"]: fact for fact in facts}
    for section in generated.get("sections", []):
        if not isinstance(section, dict) or section.get("heading") != "实习经历":
            continue
        for entry in section.get("entries", []):
            if not isinstance(entry, dict):
                continue
            fact_ids = entry.get("fact_ids") if isinstance(entry.get("fact_ids"), list) else []
            if len(fact_ids) != 1 or fact_ids[0] not in sources:
                continue
            if isinstance(entry.get("projects"), list) and len(entry["projects"]) >= 2:
                continue
            projects = _experience_projects(sources[fact_ids[0]], entry, job)
            if len(projects) >= 2:
                entry["projects"] = projects
                entry["items"] = []


def _normalize_generated_sections(generated: dict[str, Any], facts: list[dict[str, Any]]) -> None:
    """Make model output conform to the resume's fixed section taxonomy."""
    fact_types = {fact["id"]: fact["fact_type"] for fact in facts}
    allowed_headings = ("实习经历", "项目经历", "专业技能", "竞赛与荣誉")
    grouped: dict[str, dict[str, Any]] = {}

    def add_entry(heading: str, entry: dict[str, Any]) -> None:
        grouped.setdefault(heading, {"heading": heading, "entries": []})["entries"].append(entry)

    def add_item(heading: str, item: dict[str, Any]) -> None:
        grouped.setdefault(heading, {"heading": heading, "items": []})["items"].append(item)

    def fact_type(value: dict[str, Any]) -> str:
        ids = value.get("fact_ids") if isinstance(value.get("fact_ids"), list) else []
        return next((fact_types.get(fact_id, "") for fact_id in ids if fact_id in fact_types), "")

    for section in generated.get("sections", []):
        if not isinstance(section, dict):
            continue
        raw_heading = str(section.get("heading") or "")
        for entry in section.get("entries", []):
            if not isinstance(entry, dict):
                continue
            entry_type = fact_type(entry)
            heading = "实习经历" if entry_type == "experience" else "项目经历"
            if entry_type not in {"experience", "project"}:
                heading = "实习经历" if raw_heading == "实习经历" else "项目经历"
            add_entry(heading, entry)
        for item in section.get("items", []):
            if not isinstance(item, dict):
                continue
            item_type = fact_type(item)
            if item_type == "skill":
                heading = "专业技能"
            elif item_type in {"award", "certificate"}:
                heading = "竞赛与荣誉"
            elif raw_heading in allowed_headings:
                heading = raw_heading
            else:
                continue
            add_item(heading, item)

    generated["sections"] = [grouped[heading] for heading in allowed_headings if heading in grouped]
    if "专业技能" in grouped:
        generated["skills"] = []


async def _owned_fact(db: AsyncSession, user_id: int, fact_id: int) -> CareerFact:
    fact = await db.scalar(select(CareerFact).where(CareerFact.id == fact_id, CareerFact.user_id == user_id))
    if not fact:
        raise HTTPException(status_code=404, detail="Career fact not found")
    return fact


async def _owned_job(db: AsyncSession, user_id: int, job_id: int) -> JobPosting:
    job = await db.scalar(select(JobPosting).where(JobPosting.id == job_id, JobPosting.user_id == user_id))
    if not job:
        raise HTTPException(status_code=404, detail="Job posting not found")
    return job


async def _owned_resume(db: AsyncSession, user_id: int, resume_id: int) -> ResumeDocument:
    document = await db.scalar(
        select(ResumeDocument).where(
            ResumeDocument.id == resume_id,
            ResumeDocument.user_id == user_id,
        )
    )
    if not document:
        raise HTTPException(status_code=404, detail="Resume document not found")
    return document


async def _owned_knowledge_document(db: AsyncSession, user_id: int, document_id: int) -> CareerKnowledgeDocument:
    document = await db.scalar(
        select(CareerKnowledgeDocument).where(
            CareerKnowledgeDocument.id == document_id,
            CareerKnowledgeDocument.user_id == user_id,
        )
    )
    if not document:
        raise HTTPException(status_code=404, detail="Knowledge document not found")
    return document


def _knowledge_document_response(document: CareerKnowledgeDocument) -> CareerKnowledgeDocumentRead:
    return CareerKnowledgeDocumentRead(
        id=document.id,
        fact_id=document.fact_id,
        title=document.title,
        file_name=document.file_name,
        document_type=document.document_type,
        content_type=document.content_type,
        content_text=document.content_text,
        metadata=_json_load(document.metadata_json, {}),
        source_hash=document.source_hash,
        is_archived=document.is_archived,
        created_at=document.created_at,
        updated_at=document.updated_at,
    )


@router.get("/documents", response_model=list[CareerKnowledgeDocumentRead])
async def list_knowledge_documents(
    include_archived: bool = False,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> list[CareerKnowledgeDocumentRead]:
    query = select(CareerKnowledgeDocument).where(CareerKnowledgeDocument.user_id == current_user.id)
    if not include_archived:
        query = query.where(CareerKnowledgeDocument.is_archived.is_(False))
    rows = (await db.scalars(query.order_by(CareerKnowledgeDocument.updated_at.desc()))).all()
    return [_knowledge_document_response(document) for document in rows]


@router.post("/documents/upload", response_model=CareerKnowledgeDocumentRead, status_code=status.HTTP_201_CREATED)
async def upload_knowledge_document(
    file: UploadFile = File(...),
    fact_id: int = Form(...),
    title: str | None = Form(default=None),
    project_key: str | None = Form(default=None),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> CareerKnowledgeDocumentRead:
    file_name = Path(file.filename or "uploaded-document").name[:255]
    if Path(file_name).suffix.lower() != ".md":
        raise HTTPException(status_code=400, detail="技术资料目前只支持 Markdown（.md）文件")
    fact = await _owned_fact(db, current_user.id, fact_id)
    if fact.fact_type not in {"project", "experience"}:
        raise HTTPException(status_code=400, detail="技术文档只能绑定到项目或实习经历事实")
    data = await file.read(10 * 1024 * 1024 + 1)
    try:
        parsed = parse_document(file_name, file.content_type, data, "technical_doc")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    fact_content = _json_load(fact.content_json, {})
    fact_projects = fact_content.get("projects") if isinstance(fact_content, dict) else []
    single_fact_project = fact_projects[0] if isinstance(fact_projects, list) and len(fact_projects) == 1 and isinstance(fact_projects[0], dict) else None
    requested_title = str(title or "").strip()
    title_value = (
        requested_title
        or (single_fact_project or {}).get("title")
        or (fact_content.get("title") if isinstance(fact_content, dict) else None)
        or Path(file_name).stem
        or "未命名技术资料"
    ).strip()[:255]
    resolved_project_key = (
        str(project_key or "").strip()
        or (single_fact_project or {}).get("project_key")
        or (fact_content.get("project_key") if isinstance(fact_content, dict) else None)
        or stable_project_key(title_value)
    )
    metadata = dict(parsed["metadata"])
    metadata.update({
        "project_key": str(resolved_project_key),
        "claim_linking_version": CLAIM_LINKING_VERSION,
    })
    document = CareerKnowledgeDocument(
        user_id=current_user.id,
        fact_id=fact_id,
        title=title_value,
        file_name=file_name,
        document_type=parsed["document_type"],
        content_type=file.content_type or "application/octet-stream",
        content_text=parsed["content_text"],
        metadata_json=json.dumps(metadata, ensure_ascii=False),
        source_hash=parsed["source_hash"],
    )
    db.add(document)
    await db.flush()
    await _replace_knowledge_document_chunks(db, document, fact)
    await db.commit()
    await db.refresh(document)
    await _enqueue_career_evidence_index(document.id, current_user)
    return _knowledge_document_response(document)


@router.put("/documents/{document_id}", response_model=CareerKnowledgeDocumentRead)
async def update_knowledge_document(
    document_id: int,
    payload: CareerKnowledgeDocumentUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CareerKnowledgeDocumentRead:
    document = await _owned_knowledge_document(db, current_user.id, document_id)
    updates = payload.model_dump(exclude_unset=True)
    rebuild_chunks = False
    if "title" in updates:
        title = updates["title"].strip()
        if not title:
            raise HTTPException(status_code=400, detail="资料名称不能为空")
        document.title = title
        metadata = _json_load(document.metadata_json, {})
        if not metadata.get("project_key"):
            metadata["project_key"] = stable_project_key(title)
        metadata["claim_linking_version"] = CLAIM_LINKING_VERSION
        document.metadata_json = json.dumps(metadata, ensure_ascii=False)
        rebuild_chunks = True
    if "document_type" in updates:
        document.document_type = updates["document_type"]
    if "content_text" in updates:
        content_text = updates["content_text"].strip()
        if not content_text:
            raise HTTPException(status_code=400, detail="资料正文不能为空")
        document.content_text = content_text
        metadata = _json_load(document.metadata_json, {})
        metadata.update({
            "edited_in_ui": True,
            "character_count": len(document.content_text),
            "parser": "editor",
            "claim_linking_version": CLAIM_LINKING_VERSION,
        })
        document.metadata_json = json.dumps(metadata, ensure_ascii=False)
        document.source_hash = edited_source_hash(document.content_text)
        rebuild_chunks = True
    if "is_archived" in updates:
        document.is_archived = updates["is_archived"]
    if rebuild_chunks:
        await _replace_knowledge_document_chunks(db, document)
    await db.commit()
    await db.refresh(document)
    await _enqueue_career_evidence_index(document.id, current_user)
    return _knowledge_document_response(document)


@router.delete("/documents/{document_id}", response_model=CareerKnowledgeDocumentRead)
async def archive_knowledge_document(
    document_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CareerKnowledgeDocumentRead:
    document = await _owned_knowledge_document(db, current_user.id, document_id)
    document.is_archived = True
    await db.commit()
    await db.refresh(document)
    await _enqueue_career_evidence_index(document.id, current_user)
    return _knowledge_document_response(document)


@router.get("/facts", response_model=list[CareerFactRead])
async def list_facts(
    include_archived: bool = False,
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> list[CareerFactRead]:
    query = select(CareerFact).where(CareerFact.user_id == current_user.id)
    if not include_archived:
        query = query.where(CareerFact.is_archived.is_(False))
    rows = (await db.scalars(query.order_by(CareerFact.updated_at.desc()))).all()
    return [_fact_response(fact) for fact in rows]


@router.post("/facts", response_model=CareerFactRead, status_code=status.HTTP_201_CREATED)
async def create_fact(
    payload: CareerFactCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CareerFactRead:
    content = normalize_project_claims(payload.content, payload.title)
    fact = CareerFact(
        user_id=current_user.id,
        fact_type=payload.fact_type,
        title=payload.title,
        content_json=json.dumps(content, ensure_ascii=False),
        tags_json=json.dumps(payload.tags, ensure_ascii=False),
        evidence=payload.evidence,
        source_resume_name=current_user.resume_file_name,
        is_verified=payload.is_verified,
    )
    db.add(fact)
    await db.commit()
    await db.refresh(fact)
    return _fact_response(fact)


@router.put("/facts/{fact_id}", response_model=CareerFactRead)
async def update_fact(
    fact_id: int,
    payload: CareerFactUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CareerFactRead:
    fact = await _owned_fact(db, current_user.id, fact_id)
    updates = payload.model_dump(exclude_unset=True)
    next_title = str(updates.get("title") or fact.title)
    rebuild_documents = "content" in updates or "title" in updates
    if "content" in updates:
        fact.content_json = json.dumps(
            normalize_project_claims(updates.pop("content"), next_title),
            ensure_ascii=False,
        )
    elif "title" in updates:
        fact.content_json = json.dumps(
            normalize_project_claims(_json_load(fact.content_json, {}), next_title),
            ensure_ascii=False,
        )
    if "tags" in updates:
        fact.tags_json = json.dumps(updates.pop("tags"), ensure_ascii=False)
    for field, value in updates.items():
        setattr(fact, field, value)
    linked_documents: list[CareerKnowledgeDocument] = []
    if rebuild_documents:
        linked_documents = (
            await db.scalars(
                select(CareerKnowledgeDocument).where(
                    CareerKnowledgeDocument.user_id == current_user.id,
                    CareerKnowledgeDocument.fact_id == fact.id,
                    CareerKnowledgeDocument.is_archived.is_(False),
                )
            )
        ).all()
        for document in linked_documents:
            await _replace_knowledge_document_chunks(db, document, fact)
    await db.commit()
    await db.refresh(fact)
    for document in linked_documents:
        await _enqueue_career_evidence_index(document.id, current_user)
    return _fact_response(fact)


@router.delete("/facts/{fact_id}", response_model=CareerFactRead)
async def archive_fact(
    fact_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> CareerFactRead:
    fact = await _owned_fact(db, current_user.id, fact_id)
    fact.is_archived = True
    await db.commit()
    await db.refresh(fact)
    return _fact_response(fact)


@router.delete("/facts/{fact_id}/permanently", status_code=status.HTTP_204_NO_CONTENT)
async def delete_fact_permanently(
    fact_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    fact = await _owned_fact(db, current_user.id, fact_id)
    await db.delete(fact)
    await db.commit()


@router.post("/facts/extract", response_model=FactExtractionResponse)
async def extract_resume_facts(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> FactExtractionResponse:
    resume_text = (current_user.resume_text or "").strip()
    if not resume_text:
        raise HTTPException(status_code=400, detail="Upload a resume before extracting career facts")
    try:
        raw_facts = await career_studio.extract_facts(resume_text)
        facts: list[CareerFactCreate] = []
        warnings: list[FactExtractionWarning] = []
        for index, item in enumerate(raw_facts):
            try:
                facts.append(CareerFactCreate.model_validate(item))
            except Exception as exc:
                title = item.get("title", "") if isinstance(item, dict) else ""
                warnings.append(FactExtractionWarning(
                    index=index,
                    title=str(title)[:255],
                    reason=str(exc).split("\n", 1)[0][:500],
                ))
        rejected_count = len(warnings)
        if not facts and raw_facts:
            status_value = "failed_validation"
            message = "模型返回了事实，但没有任何一条通过字段校验。"
        elif not facts:
            status_value = "empty"
            message = "模型没有从当前简历中提取到有效事实。"
        elif warnings:
            status_value = "partial"
            message = f"已识别 {len(facts)} 条事实，另有 {rejected_count} 条需要检查。"
        else:
            status_value = "completed"
            message = f"已识别 {len(facts)} 条待确认事实。"
        return FactExtractionResponse(
            facts=facts,
            status=status_value,
            accepted_count=len(facts),
            rejected_count=rejected_count,
            warnings=warnings,
            message=message,
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.post("/facts/extract-from-markdown", response_model=MarkdownFactExtractionResponse, status_code=status.HTTP_202_ACCEPTED)
async def extract_fact_from_markdown(
    files: list[UploadFile] | None = File(default=None),
    file: UploadFile | None = File(default=None),
    metadata: str = Form(default="[]"),
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> MarkdownFactExtractionResponse:
    uploads = [item for item in (files or []) if item is not None]
    if file is not None:
        uploads.insert(0, file)
    if not uploads:
        raise HTTPException(status_code=400, detail="至少上传一个 Markdown 项目文档")
    try:
        raw_metadata = json.loads(metadata or "[]")
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=400, detail="项目元数据格式无效，请重新选择文件") from exc
    if raw_metadata and (not isinstance(raw_metadata, list) or len(raw_metadata) != len(uploads)):
        raise HTTPException(status_code=400, detail="项目元数据数量必须与上传文件数量一致")

    parsed_uploads: list[tuple[str, UploadFile, dict[str, Any], dict[str, str]]] = []
    try:
        for index, upload in enumerate(uploads):
            file_name = Path(upload.filename or "uploaded-document").name[:255]
            if Path(file_name).suffix.lower() != ".md":
                raise HTTPException(status_code=400, detail=f"{file_name} 不是 Markdown（.md）文件")
            data = await upload.read(10 * 1024 * 1024 + 1)
            parsed = parse_document(file_name, upload.content_type, data, "technical_doc")
            project_metadata = _normalize_project_upload_metadata(
                raw_metadata[index] if isinstance(raw_metadata, list) and index < len(raw_metadata) else {},
                file_name,
            )
            source_document = {
                "file_name": file_name,
                "title": project_metadata["title"],
                "project_metadata": project_metadata,
                "document_type": parsed["document_type"],
                "content_type": upload.content_type or "text/markdown",
                "character_count": parsed["metadata"].get("character_count", len(parsed["content_text"])),
                "source_hash": parsed["source_hash"],
            }
            parsed_uploads.append((file_name, upload, parsed, project_metadata | {"source_document": source_document}))
        job_ids: list[str] = []
        source_documents: list[dict[str, Any]] = []
        for file_name, _upload, parsed, project_metadata in parsed_uploads:
            source_document = project_metadata.pop("source_document")
            queue_job = enqueue_career_fact_job(
                {
                    "file_name": file_name,
                    "content_text": parsed["content_text"],
                    "source_document": source_document,
                    "project_metadata": project_metadata,
                },
                current_user.id,
            )
            job_ids.append(queue_job.id)
            source_documents.append(source_document)
    except QueueUnavailable as exc:
        raise HTTPException(status_code=503, detail="事实提炼队列暂时不可用，请稍后重试。") from exc
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Markdown 事实任务创建失败：{str(exc).splitlines()[0][:300]}") from exc

    return MarkdownFactExtractionResponse(
        job_id=job_ids[0],
        job_ids=job_ids,
        source_document=source_documents[0],
        source_documents=source_documents,
        status="queued",
        message=f"已上传 {len(job_ids)} 个项目文档，正在分别提炼项目事实。",
    )


@router.get("/facts/extract-from-markdown/jobs/{job_id}", response_model=MarkdownFactExtractionResponse)
async def read_markdown_fact_job(
    job_id: str,
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> MarkdownFactExtractionResponse:
    try:
        job = get_career_fact_job(job_id)
    except QueueUnavailable as exc:
        raise HTTPException(status_code=503, detail="事实提炼队列暂时不可用，请稍后重试。") from exc
    except Exception as exc:
        raise HTTPException(status_code=404, detail="事实提炼任务不存在或已过期。") from exc
    if str(job.meta.get("user_id")) != str(current_user.id):
        raise HTTPException(status_code=404, detail="事实提炼任务不存在。")

    status_value = job.get_status(refresh=True)
    if status_value in {"queued", "started", "deferred", "scheduled"}:
        return MarkdownFactExtractionResponse(job_id=job.id, status="processing", message="AI 正在提炼项目事实，请稍候。")
    if status_value == "failed":
        return MarkdownFactExtractionResponse(job_id=job.id, status="failed", message="项目提炼任务异常终止，请稍后重试；若持续失败请联系管理员查看任务日志。")
    if status_value != "finished" or not isinstance(job.result, dict):
        return MarkdownFactExtractionResponse(job_id=job.id, status="processing", message="AI 正在提炼项目事实，请稍候。")
    try:
        result = job.result
        raw_facts = result.get("facts") or ([] if not result.get("fact") else [result.get("fact")])
        facts = [CareerFactCreate.model_validate(item) for item in raw_facts]
        return MarkdownFactExtractionResponse(
            job_id=job.id,
            job_ids=[job.id],
            fact=facts[0] if len(facts) == 1 else None,
            facts=facts,
            source_document=result.get("source_document") or {},
            source_documents=[result.get("source_document") or {}],
            warnings=result.get("warnings") or [],
            quality=result.get("quality") or {},
            status=result.get("status") or "draft",
            message=result.get("message") or "已从 Markdown 提取项目事实草稿，请核对后保存。",
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Markdown 事实结果校验失败：{str(exc).splitlines()[0][:300]}") from exc


@router.post("/profile/import", response_model=ResumeProfileImportResponse)
async def import_resume_profile(
    payload: ResumeProfileImportRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ResumeProfileImportResponse:
    """Import the prototype's JSON format into the authenticated user's workspace."""
    root = _resume_profile_root(payload.draft)
    personal = _profile_personal(root)
    contact = personal.get("contact") if isinstance(personal.get("contact"), dict) else {}

    full_name = _profile_value(personal, "name", "full_name")
    target_role = _profile_value(personal, "target", "target_role")
    phone = _profile_value(contact, "手机", "phone") or _profile_value(root, "phone")
    email = _profile_value(contact, "邮箱", "email") or _profile_value(root, "email")
    if full_name:
        current_user.full_name = full_name[:255]
    if target_role:
        current_user.target_role = target_role[:255]
    if phone:
        current_user.phone = phone[:64]
    if email:
        current_user.email = email[:255]

    education_records: list[dict[str, str]] = []
    for entry in _profile_section(root, "education"):
        if isinstance(entry, str):
            education_records.append({"school": entry[:255], "degree": "", "major": "", "start_date": "", "end_date": "", "details": ""})
            continue
        if not isinstance(entry, dict):
            continue
        education_records.append({
            "school": _profile_value(entry, "school", "title")[:255],
            "degree": _profile_value(entry, "degree")[:128],
            "major": _profile_value(entry, "major")[:255],
            "start_date": _profile_value(entry, "startDate", "start_date")[:32],
            "end_date": _profile_value(entry, "endDate", "end_date")[:32],
            "rank": _profile_value(entry, "rank")[:128],
            "gpa": _profile_value(entry, "gpa")[:64],
            "english_level": _profile_value(entry, "english_level", "englishLevel")[:128],
            "details": _profile_value(entry, "details")[:2000],
        })
    if education_records:
        current_user.education_json = json.dumps(education_records, ensure_ascii=False)

    existing_rows = (await db.scalars(select(CareerFact).where(CareerFact.user_id == current_user.id))).all()
    existing_keys = {(fact.fact_type, fact.title.strip().lower()) for fact in existing_rows}
    imported = 0
    skipped = 0
    for item in _imported_fact_payload(root):
        key = (item["fact_type"], item["title"].strip().lower())
        if key in existing_keys:
            skipped += 1
            continue
        db.add(CareerFact(
            user_id=current_user.id,
            fact_type=item["fact_type"],
            title=item["title"],
            content_json=json.dumps(item["content"], ensure_ascii=False),
            tags_json=json.dumps(item["tags"], ensure_ascii=False),
            evidence=item["evidence"],
            source_resume_name=current_user.resume_file_name or "prototype-json-import",
            is_verified=False,
        ))
        existing_keys.add(key)
        imported += 1

    await db.commit()
    return ResumeProfileImportResponse(
        imported_facts=imported,
        skipped_facts=skipped,
        updated_profile=bool(full_name or target_role or phone or email or education_records),
        education_records=len(education_records),
    )


@router.get("/jobs", response_model=list[JobPostingRead])
async def list_jobs(
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> list[JobPostingRead]:
    rows = (await db.scalars(select(JobPosting).where(JobPosting.user_id == current_user.id).order_by(JobPosting.updated_at.desc()))).all()
    return [_job_response(job) for job in rows]


@router.post("/jobs/import", response_model=JobPostingRead, status_code=status.HTTP_201_CREATED)
async def import_job(
    payload: JobImportRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JobPostingRead:
    started_at = perf_counter()
    source_url = str(payload.source_url) if payload.source_url else None
    try:
        raw_content = payload.raw_content or await career_studio.fetch_job_page(source_url or "")
        if not raw_content or len(raw_content) < 20:
            raise ValueError("Paste a complete job description or provide a readable job URL")
        normalized = await career_studio.normalize_job(raw_content, source_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job = JobPosting(
        user_id=current_user.id,
        title=normalized.get("title") or "Untitled position",
        company=normalized.get("company") or "",
        source_url=source_url,
        raw_content=raw_content,
        normalized_json=json.dumps(normalized, ensure_ascii=False),
        extraction_status="ready",
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    logger.info(
        "Career job import completed in %.0fms source_url=%s raw_chars=%s job_id=%s",
        (perf_counter() - started_at) * 1000,
        bool(source_url),
        len(raw_content),
        job.id,
    )
    return _job_response(job)


@router.put("/jobs/{job_id}", response_model=JobPostingRead)
async def update_job(
    job_id: int,
    payload: JobPostingUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JobPostingRead:
    job = await _owned_job(db, current_user.id, job_id)
    updates = payload.model_dump(exclude_unset=True)
    normalized = updates.pop("normalized", None)
    if normalized is not None:
        job.normalized_json = json.dumps(normalized, ensure_ascii=False)
    for field, value in updates.items():
        setattr(job, field, value)
    await db.commit()
    await db.refresh(job)
    return _job_response(job)


@router.post("/jobs/{job_id}/refresh", response_model=JobPostingRead)
async def refresh_job(
    job_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> JobPostingRead:
    job = await _owned_job(db, current_user.id, job_id)
    if not job.source_url:
        raise HTTPException(status_code=400, detail="This job was pasted manually and has no URL to refresh")
    try:
        raw_content = await career_studio.fetch_job_page(job.source_url)
        normalized = await career_studio.normalize_job(raw_content, job.source_url)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    job.raw_content = raw_content
    job.normalized_json = json.dumps(normalized, ensure_ascii=False)
    job.title = normalized.get("title") or job.title
    job.company = normalized.get("company") or job.company
    job.extraction_status = "ready"
    await db.commit()
    await db.refresh(job)
    return _job_response(job)


@router.delete("/jobs/{job_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_job(
    job_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    job = await _owned_job(db, current_user.id, job_id)
    await db.execute(
        delete(ResumeDocument).where(
            ResumeDocument.user_id == current_user.id,
            ResumeDocument.job_id == job.id,
        )
    )
    await db.delete(job)
    await db.commit()


@router.get("/resumes", response_model=list[ResumeDocumentRead])
async def list_resume_documents(
    job_id: int | None = Query(default=None),
    db: Annotated[AsyncSession, Depends(get_db)] = None,
    current_user: Annotated[User, Depends(get_current_user)] = None,
) -> list[ResumeDocumentRead]:
    query = select(ResumeDocument).where(ResumeDocument.user_id == current_user.id)
    if job_id is not None:
        query = query.where(ResumeDocument.job_id == job_id)
    rows = (await db.scalars(query.order_by(ResumeDocument.updated_at.desc()))).all()
    return [_resume_response(document) for document in rows]


@router.get("/resumes/{resume_id}/tex")
async def download_resume_tex_bundle(
    resume_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    document = await _owned_resume(db, current_user.id, resume_id)
    bundle = await asyncio.to_thread(
        build_tex_bundle,
        _json_load(document.content_json, {}),
        current_user,
        document.title,
    )
    return Response(
        content=bundle,
        media_type="application/zip",
        headers={"Content-Disposition": 'attachment; filename="resume-tex-source.zip"'},
    )


@router.get("/resumes/{resume_id}/pdf")
async def download_resume_pdf(
    resume_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> Response:
    document = await _owned_resume(db, current_user.id, resume_id)
    content = _json_load(document.content_json, {})
    job = None
    if document.job_id:
        job = await db.scalar(select(JobPosting).where(JobPosting.id == document.job_id, JobPosting.user_id == current_user.id))
    try:
        pdf = await asyncio.to_thread(
            compile_resume_pdf,
            content,
            current_user,
            document.title,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                "attachment; filename*=UTF-8''"
                + quote(
                    "--".join(
                        [
                            _filename_part(current_user.full_name, "未填写姓名"),
                            _filename_part(job.company if job else "", "未指定公司"),
                            _filename_part((job.title if job else "") or content.get("headline"), "未指定岗位"),
                        ]
                    )
                    + ".pdf"
                )
            )
        },
    )


@router.put("/resumes/{resume_id}", response_model=ResumeDocumentRead)
async def update_resume_document(
    resume_id: int,
    payload: ResumeDocumentUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ResumeDocumentRead:
    document = await _owned_resume(db, current_user.id, resume_id)
    updates = payload.model_dump(exclude_unset=True)
    if "content" in updates:
        content = updates.pop("content")
        if not isinstance(content, dict) or not content:
            raise HTTPException(status_code=422, detail="Resume content must be a non-empty object")
        document.content_json = json.dumps(content, ensure_ascii=False)
        document.status = "edited"
    for field, value in updates.items():
        setattr(document, field, value)
    await db.commit()
    await db.refresh(document)
    return _resume_response(document)


@router.post("/resumes/generate", response_model=ResumeDocumentRead, status_code=status.HTTP_201_CREATED)
async def generate_tailored_resume(
    payload: TailoredResumeRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> ResumeDocumentRead:
    job = await _owned_job(db, current_user.id, payload.job_id)
    profile_education = _profile_education(current_user)
    fact_query = select(CareerFact).where(
        CareerFact.user_id == current_user.id,
        CareerFact.is_verified.is_(True),
        CareerFact.is_archived.is_(False),
    )
    if payload.fact_ids:
        fact_query = fact_query.where(CareerFact.id.in_(payload.fact_ids))
    facts = (await db.scalars(fact_query)).all()
    if profile_education:
        facts = [fact for fact in facts if fact.fact_type != "education"]
    if not facts:
        raise HTTPException(status_code=400, detail="Verify at least one career fact before generating a tailored resume")

    fact_payload = [
        {
            "id": fact.id,
            "fact_type": fact.fact_type,
            "title": fact.title,
            "content": sanitize_resume_content(_json_load(fact.content_json, {}), fact.title, fact.fact_type),
            "tags": _json_load(fact.tags_json, []),
            "evidence": fact.evidence,
        }
        for fact in facts
    ]
    try:
        generated = await career_studio.generate_tailored_resume(
            _json_load(job.normalized_json, {}),
            fact_payload,
            has_profile_education=bool(profile_education),
        )
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    _normalize_generated_sections(generated, fact_payload)
    if profile_education:
        generated["education"] = profile_education
        generated["sections"] = [
            section for section in generated.get("sections", [])
            if isinstance(section, dict) and section.get("heading") != "教育背景"
        ]
    job_payload = _json_load(job.normalized_json, {})
    _enrich_entries_from_evidence(generated, fact_payload, job_payload)
    _expand_experience_entries(generated, fact_payload, job_payload)
    for section in generated.get("sections", []):
        if isinstance(section, dict) and section.get("heading") == "竞赛与荣誉":
            section["items"] = list(section.get("items", []))[:5]

    match = generated.pop("match_analysis", {})
    document = ResumeDocument(
        user_id=current_user.id,
        job_id=job.id,
        kind="tailored",
        title=payload.title or f"{job.title} - tailored resume",
        content_json=json.dumps(generated, ensure_ascii=False),
        match_json=json.dumps(match if isinstance(match, dict) else {}, ensure_ascii=False),
        status="draft",
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    return _resume_response(document)


@router.delete("/resumes/{resume_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resume_document(
    resume_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    current_user: Annotated[User, Depends(get_current_user)],
) -> None:
    document = await db.scalar(
        select(ResumeDocument).where(
            ResumeDocument.id == resume_id,
            ResumeDocument.user_id == current_user.id,
        )
    )
    if not document:
        raise HTTPException(status_code=404, detail="Resume document not found")
    await db.delete(document)
    await db.commit()
