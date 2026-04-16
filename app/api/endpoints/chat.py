from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse

from app.api.deps import get_streaming_service, get_current_user
from app.models.user import User as DBUser
from app.schemas.api import LLMRequest
from app.services.streaming import StreamingService
from app.utils.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()


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
    streaming_service: StreamingService = Depends(get_streaming_service)
) -> StreamingResponse:
    use_interview_mode = request.skill_name == "interview-skills" or any([request.interview_role, request.interview_level, request.interview_type])
    if use_interview_mode and not (current_user.resume_text or "").strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Please upload your resume in the profile page before starting an interview",
        )

    effective_resume_content = build_profile_resume_context(current_user) if (current_user.resume_text or "").strip() else request.resume_content
    request = request.model_copy(update={"resume_content": effective_resume_content})
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
