import asyncio
import json
import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.career import CareerFact, JobPosting, ResumeDocument
from app.models.user import User
from app.schemas.career import (
    CareerFactCreate,
    CareerFactRead,
    CareerFactUpdate,
    FactExtractionResponse,
    JobImportRequest,
    JobPostingRead,
    JobPostingUpdate,
    ResumeDocumentRead,
    ResumeDocumentUpdate,
    ResumeProfileImportRequest,
    ResumeProfileImportResponse,
    TailoredResumeRequest,
)
from app.services.career_studio import CareerStudioService
from app.services.resume_tex_renderer import build_tex_bundle, compile_resume_pdf

router = APIRouter()
career_studio = CareerStudioService()


def _json_load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _fact_response(fact: CareerFact) -> CareerFactRead:
    return CareerFactRead(
        id=fact.id,
        fact_type=fact.fact_type,
        title=fact.title,
        content=_json_load(fact.content_json, {}),
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


def _enrich_entries_from_evidence(generated: dict[str, Any], facts: list[dict[str, Any]]) -> None:
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
    fact = CareerFact(
        user_id=current_user.id,
        fact_type=payload.fact_type,
        title=payload.title,
        content_json=json.dumps(payload.content, ensure_ascii=False),
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
    if "content" in updates:
        fact.content_json = json.dumps(updates.pop("content"), ensure_ascii=False)
    if "tags" in updates:
        fact.tags_json = json.dumps(updates.pop("tags"), ensure_ascii=False)
    for field, value in updates.items():
        setattr(fact, field, value)
    await db.commit()
    await db.refresh(fact)
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
        for item in raw_facts:
            try:
                facts.append(CareerFactCreate.model_validate(item))
            except Exception:
                continue
        return FactExtractionResponse(facts=facts)
    except ValueError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
    try:
        pdf = await asyncio.to_thread(
            compile_resume_pdf,
            _json_load(document.content_json, {}),
            current_user,
            document.title,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="tailored-resume.pdf"'},
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
            "content": _json_load(fact.content_json, {}),
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
    _enrich_entries_from_evidence(generated, fact_payload)
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
