from fastapi import APIRouter, Depends, HTTPException, Query

from app.schemas.chat import (
    ChatHistoryResponse,
    ChatMessage,
    InterviewReportResponse,
    VoiceInterviewReportRequest,
)
from app.services.interview_report import InterviewReportBuilder
from app.services.vector_store import MultiTenantVectorStore
from app.api.deps import get_current_user, get_vector_store
from app.utils.logger import setup_logger

logger = setup_logger(__name__)
router = APIRouter()
report_builder = InterviewReportBuilder()


@router.get("/chats", response_model=ChatHistoryResponse)
async def get_user_chats(
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    vector_store: MultiTenantVectorStore = Depends(get_vector_store),
    current_user = Depends(get_current_user)
):
    """Get all chat messages for the current user"""
    try:
        chats = vector_store.get_chats_by_user_id(
            user_id=str(current_user.id),
            tenant_id=current_user.tenant_id,
            limit=limit,
            offset=offset
        )

        messages = [ChatMessage(**chat) for chat in chats]
        
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
    offset: int = Query(0, ge=0)

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

        messages = [ChatMessage(**msg) for msg in chat_messages]
        
        return ChatHistoryResponse(
            messages=messages,
            total=len(messages)
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error retrieving chat: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve chat")


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
