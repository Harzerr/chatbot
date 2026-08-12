from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.api import CodeRunJobResponse, CodeRunRequest
from app.services.task_queue import QueueUnavailable, enqueue_code_run_job, get_code_job

router = APIRouter()


@router.post("/run", response_model=CodeRunJobResponse, status_code=status.HTTP_202_ACCEPTED)
async def run_code(
    request: CodeRunRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> CodeRunJobResponse:
    try:
        job = enqueue_code_run_job(request.model_dump(), current_user.id)
    except QueueUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

    return CodeRunJobResponse(job_id=job.id, status="queued")


@router.get("/run/{job_id}", response_model=CodeRunJobResponse)
async def get_code_run_status(
    job_id: str,
    current_user: Annotated[User, Depends(get_current_user)],
) -> CodeRunJobResponse:
    try:
        job = get_code_job(job_id)
    except QueueUnavailable as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Code execution job not found") from exc

    if job.meta.get("user_id") != str(current_user.id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Code execution job not found")

    job_status = job.get_status(refresh=True)
    if job_status == "finished":
        from app.schemas.api import CodeRunResponse

        return CodeRunJobResponse(
            job_id=job.id,
            status="finished",
            result=CodeRunResponse.model_validate(job.return_value()),
        )
    if job_status == "failed":
        return CodeRunJobResponse(
            job_id=job.id,
            status="failed",
            error="代码执行任务失败，请检查代码或稍后重试。",
        )
    return CodeRunJobResponse(job_id=job.id, status=job_status or "queued")
