from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.api import CodeRunRequest, CodeRunResponse
from app.services.code_runner import Judge0CodeRunner

router = APIRouter()


@router.post("/run", response_model=CodeRunResponse)
async def run_code(
    request: CodeRunRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> CodeRunResponse:
    _ = current_user
    runner = Judge0CodeRunner()
    return runner.run(request)
