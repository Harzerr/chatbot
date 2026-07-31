from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.services.interview_report import InterviewReportBuilder
from app.services.vector_store import MultiTenantVectorStore
from app.api.deps import get_current_user, get_vector_store
from app.utils.logger import setup_logger

logger = setup_logger(__name__)
router = APIRouter()
report_builder = InterviewReportBuilder()


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

        return report_builder.build(chat_id=chat_id, chat_messages=chat_messages)
    except Exception as e:
        logger.error(f"Error generating chat report: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate chat report")


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
