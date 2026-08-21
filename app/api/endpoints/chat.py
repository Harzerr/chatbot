import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_streaming_service, get_current_user
from app.api.deps import get_vector_store
from app.db.session import get_db
from app.models.career import CareerKnowledgeDocument
from app.models.user import User as DBUser
from app.schemas.api import LLMRequest
from app.services.streaming import StreamingService
from app.services.vector_store import MultiTenantVectorStore
from app.services.career_knowledge import build_cached_knowledge_context
from app.services.interview_assessment import should_use_career_evidence
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()

MANUAL_FINISH_COMMAND = "__SYSTEM_END_INTERVIEW_AND_EXPORT_REPORT__"
INTERVIEW_END_MARKERS = (
    "本场面试已结束",
    "本次面试已结束",
    "本场面试结束",
    "本次面试结束",
    "面试已结束",
    "面试到此结束",
    "本场面试到此结束",
    "本次面试到此结束",
    "面试环节结束",
)


def _interview_has_ended(messages: list[dict]) -> bool:
    for message in messages:
        if message.get("user_message") == MANUAL_FINISH_COMMAND:
            return True
        assistant_message = "".join(str(message.get("assistant_message") or "").split())
        if any(marker in assistant_message for marker in INTERVIEW_END_MARKERS):
            return True
    return False


def build_profile_resume_context(current_user: DBUser) -> str:
    summary_lines = [
        f"姓名：{current_user.full_name or '未填写'}",
        f"邮箱：{current_user.email or '未填写'}",
        f"电话：{current_user.phone or '未填写'}",
        f"目标岗位：{current_user.target_role or '未填写'}",
        f"工作年限：{current_user.years_of_experience or 0} 年",
    ]
    if current_user.bio:
        summary_lines.append(f"个人简介：{current_user.bio}")

    resume_text = (current_user.resume_text or "").strip()
    return "候选人个人档案：\n" + "\n".join(summary_lines) + "\n\n候选人简历内容：\n" + resume_text

@router.post("/completions")
async def chat_completions(
    request: LLMRequest,
    current_user: Annotated[DBUser, Depends(get_current_user)],
    streaming_service: StreamingService = Depends(get_streaming_service),
    vector_store: MultiTenantVectorStore = Depends(get_vector_store),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    use_interview_mode = request.skill_name == "interview-skills" or any([request.interview_role, request.interview_level, request.interview_type])
    if use_interview_mode and not (current_user.resume_text or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please upload your resume in the profile page before starting an interview",
        )

    if use_interview_mode:
        existing_messages = await asyncio.to_thread(
            vector_store.get_chat_by_id,
            chat_id=request.chat_id,
            user_id=str(current_user.id),
            tenant_id=current_user.tenant_id,
            limit=200,
            offset=0,
        )
        if existing_messages and _interview_has_ended(existing_messages):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="该面试已经结束，不能继续作答，请查看面试报告。",
            )

    effective_resume_content = build_profile_resume_context(current_user) if (current_user.resume_text or "").strip() else request.resume_content
    knowledge_context = request.knowledge_context
    evidence_cache_hit = False
    previous_question = ""
    previous_knowledge_context = ""
    if use_interview_mode and existing_messages:
        previous_question = str(existing_messages[-1].get("assistant_message") or "")
        previous_knowledge_context = str(existing_messages[-1].get("knowledge_context") or "")
    if use_interview_mode:
        # A follow-up often omits the project name. Once a prior turn has an
        # evidence pack, inherit its project scope for the rest of the thread.
        current_turn_text = f"{previous_question}\n{request.user_message}"
        code_markers = ("代码题", "手撕代码", "实现一个", "时间复杂度", "空间复杂度", "```", "#include", "def ", "class ")
        is_code_turn = any(marker in current_turn_text.lower() for marker in code_markers)
        use_career_evidence = (not is_code_turn) and (
            bool(previous_knowledge_context) or should_use_career_evidence(current_turn_text)
        )
        if use_career_evidence:
            documents = (await db.scalars(
                select(CareerKnowledgeDocument).where(
                    CareerKnowledgeDocument.user_id == current_user.id,
                    CareerKnowledgeDocument.is_archived.is_(False),
                ).options(selectinload(CareerKnowledgeDocument.chunks)).order_by(
                    CareerKnowledgeDocument.updated_at.desc()
                )
            )).all()
            knowledge_context, evidence_cache_hit = await asyncio.to_thread(
                build_cached_knowledge_context,
                documents,
                f"{previous_question}\n{request.user_message}\n{request.jd_content or ''}\n{previous_knowledge_context[:1200]}",
                tenant_id=current_user.tenant_id,
                user_id=str(current_user.id),
                fact_id=request.knowledge_fact_id,
            )
            logger.info(
                "Interview evidence pack ready: chat_id=%s fact_id=%s cache_hit=%s chars=%s",
                request.chat_id,
                request.knowledge_fact_id,
                evidence_cache_hit,
                len(knowledge_context or ""),
            )
        else:
            knowledge_context = None
            logger.info(
                "Interview career evidence skipped: chat_id=%s question_type=non-project previous_question_len=%s",
                request.chat_id,
                len(previous_question),
            )
    request = request.model_copy(update={
        "resume_content": effective_resume_content,
        "knowledge_context": knowledge_context,
        "knowledge_context_cache_hit": evidence_cache_hit,
    })
    logger.info(
        "Received chat completions request: chat_id=%s skill=%s interview_role=%s interview_level=%s interview_type=%s user_message_len=%s resume_len=%s",
        request.chat_id,
        request.skill_name,
        request.interview_role,
        request.interview_level,
        request.interview_type,
        len(request.user_message or ""),
        len(request.resume_content or ""),
    )
    return await streaming_service.streaming_chat(request, current_user)
