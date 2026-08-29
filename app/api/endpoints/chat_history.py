import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.schemas.chat import (
    ChatDeleteResponse,
    ChatHistoryResponse,
    ChatMessage,
    InterviewReportResponse,
    InterviewSessionActionResponse,
    VoiceInterviewReportRequest,
)
from app.db.session import get_db
from app.models.interview_session import InterviewSession
from app.models.career import CareerKnowledgeDocument
from app.services.interview_report import InterviewReportBuilder
from app.services.interview_report_pdf import InterviewReportPdfBuilder, InterviewReportPdfError
from app.services.interview_evaluator import InterviewEvaluator
from app.services.vector_store import MultiTenantVectorStore
from app.schemas.evaluation import EvidenceFeedbackRequest, EvidencePack, EvaluationRequest
from app.services.career_knowledge import build_cached_evidence_pack
from app.services.interview_assessment import should_use_career_evidence
from app.services.task_queue import QueueUnavailable, enqueue_evaluation_job
from app.api.deps import get_current_user, get_vector_store
from app.utils.logger import setup_logger

logger = setup_logger(__name__)
router = APIRouter()
report_builder = InterviewReportBuilder()
report_pdf_builder = InterviewReportPdfBuilder()


def _session_payload(session: InterviewSession | None) -> dict:
    if session is None:
        return {
            "interview_status": "active",
            "interview_paused_at": None,
            "interview_paused_seconds": 0.0,
        }
    return {
        "interview_status": session.status,
        "interview_paused_at": session.paused_at.isoformat() if session.paused_at else None,
        "interview_paused_seconds": float(session.paused_seconds or 0),
    }


async def _get_owned_chat_or_404(chat_id: str, current_user, vector_store):
    messages = vector_store.get_chat_by_id(
        chat_id=chat_id,
        user_id=current_user.id,
        tenant_id=current_user.tenant_id,
        limit=200,
        offset=0,
    )
    if not messages:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview record not found")
    return messages


async def _get_session(db: AsyncSession, chat_id: str, current_user) -> InterviewSession | None:
    result = await db.execute(
        select(InterviewSession).where(
            InterviewSession.chat_id == chat_id,
            InterviewSession.user_id == current_user.id,
            InterviewSession.tenant_id == current_user.tenant_id,
        )
    )
    return result.scalar_one_or_none()


@router.get("/chats", response_model=ChatHistoryResponse)
async def get_user_chats(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    vector_store: MultiTenantVectorStore = Depends(get_vector_store),
    current_user = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get all chat messages for the current user"""
    try:
        chats = vector_store.get_chats_by_user_id(
            user_id=str(current_user.id),
            tenant_id=current_user.tenant_id,
            limit=limit,
            offset=offset
        )

        session_rows = await db.execute(
            select(InterviewSession).where(
                InterviewSession.user_id == current_user.id,
                InterviewSession.tenant_id == current_user.tenant_id,
            )
        )
        sessions = {session.chat_id: session for session in session_rows.scalars()}
        messages = [
            ChatMessage(**(chat | _session_payload(sessions.get(chat.get("chat_id", "")))))
            for chat in chats
        ]
        
        return ChatHistoryResponse(
            messages=messages,
            total=len(messages)
        )
    except Exception as e:
        logger.error(f"Error retrieving chat history: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve chat history")


@router.get("/chats/{chat_id}", response_model=ChatHistoryResponse)
async def get_chat_by_id(
    chat_id: str,
    current_user = Depends(get_current_user),
    vector_store: MultiTenantVectorStore = Depends(get_vector_store),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),

):
    """Get all messages for a specific chat ID"""
    try:
        chat_messages = vector_store.get_chat_by_id(
            chat_id=chat_id,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            limit=limit,
            offset=offset
        )

        session = await _get_session(db, chat_id, current_user)
        messages = [ChatMessage(**(msg | _session_payload(session))) for msg in chat_messages]
        
        return ChatHistoryResponse(
            messages=messages,
            total=len(messages)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving chat: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve chat")


@router.post("/chats/{chat_id}/pause", response_model=InterviewSessionActionResponse)
async def pause_chat(
    chat_id: str,
    current_user=Depends(get_current_user),
    vector_store: MultiTenantVectorStore = Depends(get_vector_store),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_chat_or_404(chat_id, current_user, vector_store)
    session = await _get_session(db, chat_id, current_user)
    if session is None:
        session = InterviewSession(
            chat_id=chat_id,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            status="paused",
            paused_at=datetime.utcnow(),
        )
        db.add(session)
    elif session.status != "paused":
        session.status = "paused"
        session.paused_at = datetime.utcnow()

    await db.commit()
    await db.refresh(session)
    return InterviewSessionActionResponse(chat_id=chat_id, status=session.status, paused_at=session.paused_at, paused_seconds=session.paused_seconds)


@router.post("/chats/{chat_id}/resume", response_model=InterviewSessionActionResponse)
async def resume_chat(
    chat_id: str,
    current_user=Depends(get_current_user),
    vector_store: MultiTenantVectorStore = Depends(get_vector_store),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_chat_or_404(chat_id, current_user, vector_store)
    session = await _get_session(db, chat_id, current_user)
    if session and session.status == "paused":
        if session.paused_at:
            session.paused_seconds += max(0.0, (datetime.utcnow() - session.paused_at).total_seconds())
        session.status = "active"
        session.paused_at = None
        await db.commit()
        await db.refresh(session)

    payload = _session_payload(session)
    return InterviewSessionActionResponse(
        chat_id=chat_id,
        status=payload["interview_status"],
        paused_at=payload["interview_paused_at"],
        paused_seconds=payload["interview_paused_seconds"],
    )


@router.delete("/chats/{chat_id}", response_model=ChatDeleteResponse)
async def delete_chat(
    chat_id: str,
    current_user=Depends(get_current_user),
    vector_store: MultiTenantVectorStore = Depends(get_vector_store),
    db: AsyncSession = Depends(get_db),
):
    await _get_owned_chat_or_404(chat_id, current_user, vector_store)
    vector_store.delete_chat_by_id(chat_id, current_user.tenant_id, current_user.id)
    await db.execute(
        delete(InterviewSession).where(
            InterviewSession.chat_id == chat_id,
            InterviewSession.user_id == current_user.id,
            InterviewSession.tenant_id == current_user.tenant_id,
        )
    )
    await db.commit()
    return ChatDeleteResponse(chat_id=chat_id, deleted=True)


@router.get("/chats/{chat_id}/report", response_model=InterviewReportResponse)
async def get_chat_report(
    chat_id: str,
    partial: bool = Query(False),
    current_user=Depends(get_current_user),
    vector_store: MultiTenantVectorStore = Depends(get_vector_store),
):
    try:
        chat_messages = vector_store.get_chat_by_id(
            chat_id=chat_id,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            limit=200,
            offset=0,
        )

        return report_builder.build(
            chat_id=chat_id,
            chat_messages=chat_messages,
            include_reference_answers=not partial,
        )
    except Exception as e:
        logger.error(f"Error generating chat report: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate chat report")


@router.get("/chats/{chat_id}/report/pdf")
async def download_chat_report_pdf(
    chat_id: str,
    current_user=Depends(get_current_user),
    vector_store: MultiTenantVectorStore = Depends(get_vector_store),
):
    """Generate a selectable-text A4 report with an available server renderer."""
    try:
        chat_messages = vector_store.get_chat_by_id(
            chat_id=chat_id,
            user_id=current_user.id,
            tenant_id=current_user.tenant_id,
            limit=200,
            offset=0,
        )
        if not chat_messages:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Interview record not found")

        report = report_builder.build(
            chat_id=chat_id,
            chat_messages=chat_messages,
            include_reference_answers=False,
        )
        generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")
        pdf_bytes = await asyncio.to_thread(report_pdf_builder.build, report, generated_at)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'attachment; filename="interview-report-{chat_id}.pdf"'},
        )
    except HTTPException:
        raise
    except InterviewReportPdfError as exc:
        logger.error("Failed to compile interview report PDF for %s: %s", chat_id, exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        logger.error("Error generating interview report PDF for %s: %s", chat_id, exc, exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate interview report PDF") from exc


@router.post("/chats/{chat_id}/messages/{point_id}/evaluation/retry")
async def retry_chat_evaluation(
    chat_id: str,
    point_id: str,
    current_user=Depends(get_current_user),
    vector_store: MultiTenantVectorStore = Depends(get_vector_store),
    db: AsyncSession = Depends(get_db),
):
    """Requeue one failed or fallback evaluation using the original stored interview turn."""
    messages = await _get_owned_chat_or_404(chat_id, current_user, vector_store)
    target_index = next((index for index, item in enumerate(messages) if str(item.get("id")) == str(point_id)), None)
    if target_index is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation point not found")

    target = messages[target_index]
    evaluation = target.get("evaluation") or {}
    # Allow an explicit re-evaluation even when the previous run completed.
    # This is useful after changing prompts, evidence extraction, or scoring
    # code; the original turn is always used as the source of truth.

    previous_question = ""
    for message in messages[:target_index]:
        if message.get("assistant_message"):
            previous_question = str(message["assistant_message"])
    if not previous_question or not target.get("user_message"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少原始面试问题或回答，无法重试")

    evidence_pack = target.get("evidence_pack")
    knowledge_context = target.get("knowledge_context")
    evidence_cache_hit = False
    if should_use_career_evidence(previous_question) or knowledge_context:
        documents = (await db.scalars(
            select(CareerKnowledgeDocument).where(
                CareerKnowledgeDocument.user_id == current_user.id,
                CareerKnowledgeDocument.is_archived.is_(False),
            ).options(selectinload(CareerKnowledgeDocument.chunks)).order_by(
                CareerKnowledgeDocument.updated_at.desc()
            )
        )).all()
        rebuilt_pack, evidence_cache_hit = await asyncio.to_thread(
            build_cached_evidence_pack,
            documents,
            f"{previous_question}\n{target.get('user_message') or ''}\n{target.get('jd_content') or ''}",
            tenant_id=current_user.tenant_id,
            user_id=str(current_user.id),
        )
        evidence_pack = EvidencePack.model_validate(rebuilt_pack)
        knowledge_context = evidence_pack.context

    request = EvaluationRequest(
        previous_question=previous_question,
        user_answer=str(target.get("user_message") or ""),
        interview_role=target.get("interview_role"),
        interview_level=target.get("interview_level"),
        interview_type=target.get("interview_type"),
        target_company=target.get("target_company"),
        jd_content=target.get("jd_content"),
        resume_content=target.get("resume_content"),
        code_execution=target.get("code_execution"),
        knowledge_context=knowledge_context,
        evidence_pack=evidence_pack,
        knowledge_context_cache_hit=evidence_cache_hit,
        evidence_feedback=target.get("evidence_feedback") or [],
    )
    payload = {
        "point_id": str(point_id),
        "tenant_id": str(current_user.tenant_id),
        "user_id": str(current_user.id),
        "chat_id": str(chat_id),
        "request": request.model_dump(mode="json"),
        "force_refresh": True,
    }

    vector_store.update_conversation_evaluation(
        point_id=str(point_id),
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        chat_id=chat_id,
        status="queued",
        error_message="",
    )
    try:
        job = await asyncio.to_thread(enqueue_evaluation_job, payload)
        await asyncio.to_thread(
            vector_store.set_conversation_evaluation_job_id,
            point_id=str(point_id),
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            chat_id=chat_id,
            job_id=job.id,
        )
        return {"point_id": str(point_id), "job_id": job.id, "status": "queued"}
    except QueueUnavailable as exc:
        vector_store.update_conversation_evaluation(
            point_id=str(point_id),
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            chat_id=chat_id,
            status="failed",
            error_message=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/chats/{chat_id}/messages/{point_id}/evaluation/evidence-feedback")
async def submit_evidence_feedback(
    chat_id: str,
    point_id: str,
    request: EvidenceFeedbackRequest,
    current_user=Depends(get_current_user),
    vector_store: MultiTenantVectorStore = Depends(get_vector_store),
):
    """Persist user evidence verification and force a fresh evaluation."""
    messages = await _get_owned_chat_or_404(chat_id, current_user, vector_store)
    target = next((item for item in messages if str(item.get("id")) == str(point_id)), None)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Evaluation point not found")

    stored_evidence_items = (target.get("evaluation") or {}).get("knowledge_evidence_items") or []
    _, _, derived_evidence_items = InterviewEvaluator.extract_knowledge_evidence(
        target.get("knowledge_context")
    )
    evidence_items = stored_evidence_items or [
        item.model_dump(mode="json") for item in derived_evidence_items
    ]
    known_ids = {
        str(item.get("evidence_id"))
        for item in evidence_items
        if item.get("evidence_id")
    }
    unknown_ids = [item.evidence_id for item in request.feedback if item.evidence_id not in known_ids]
    if unknown_ids:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"存在不属于本题的证据：{', '.join(unknown_ids[:3])}",
        )

    previous_question = ""
    target_index = messages.index(target)
    for message in messages[:target_index]:
        if message.get("assistant_message"):
            previous_question = str(message["assistant_message"])
    if not previous_question or not target.get("user_message"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="缺少原始面试问题或回答，无法重新评估")

    feedback = [item.model_dump(mode="json") for item in request.feedback]

    # Backfill legacy interview turns before requeueing so the report can render
    # the exact same evidence IDs that the feedback endpoint validates.
    if derived_evidence_items and not stored_evidence_items:
        derived_evidence, derived_ids, _ = InterviewEvaluator.extract_knowledge_evidence(
            target.get("knowledge_context")
        )
        legacy_evaluation = dict(target.get("evaluation") or {})
        legacy_evaluation["knowledge_evidence"] = derived_evidence
        legacy_evaluation["knowledge_evidence_ids"] = derived_ids
        legacy_evaluation["knowledge_evidence_items"] = evidence_items
        legacy_evaluation["knowledge_evidence_source"] = "career_rag"
        vector_store.update_conversation_evaluation(
            point_id=str(point_id),
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            chat_id=chat_id,
            status="queued",
            evaluation=legacy_evaluation,
        )

    evaluation_request = EvaluationRequest(
        previous_question=previous_question,
        user_answer=str(target.get("user_message") or ""),
        interview_role=target.get("interview_role"),
        interview_level=target.get("interview_level"),
        interview_type=target.get("interview_type"),
        target_company=target.get("target_company"),
        jd_content=target.get("jd_content"),
        resume_content=target.get("resume_content"),
        code_execution=target.get("code_execution"),
        knowledge_context=target.get("knowledge_context"),
        evidence_pack=target.get("evidence_pack"),
        evidence_feedback=feedback,
    )
    payload = {
        "point_id": str(point_id),
        "tenant_id": str(current_user.tenant_id),
        "user_id": str(current_user.id),
        "chat_id": str(chat_id),
        "request": evaluation_request.model_dump(mode="json"),
        "force_refresh": True,
    }

    vector_store.update_conversation_evaluation(
        point_id=str(point_id),
        tenant_id=current_user.tenant_id,
        user_id=current_user.id,
        chat_id=chat_id,
        status="queued",
        evidence_feedback=feedback,
        error_message="",
    )
    try:
        job = await asyncio.to_thread(enqueue_evaluation_job, payload)
        await asyncio.to_thread(
            vector_store.set_conversation_evaluation_job_id,
            point_id=str(point_id),
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            chat_id=chat_id,
            job_id=job.id,
        )
        return {"point_id": str(point_id), "job_id": job.id, "status": "queued", "feedback": feedback}
    except QueueUnavailable as exc:
        vector_store.update_conversation_evaluation(
            point_id=str(point_id),
            tenant_id=current_user.tenant_id,
            user_id=current_user.id,
            chat_id=chat_id,
            status="failed",
            evidence_feedback=feedback,
            error_message=str(exc),
        )
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.post("/voice/report", response_model=InterviewReportResponse)
async def get_voice_interview_report(
    request: VoiceInterviewReportRequest,
    current_user=Depends(get_current_user),
):
    try:
        chat_id = request.chat_id or f"voice-{current_user.id}"
        return report_builder.build_from_transcript(chat_id=chat_id, request=request)
    except Exception as e:
        logger.error(f"Error generating voice interview report: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate voice interview report")
