from app.schemas.api import CodeRunRequest
from app.services.code_runner import Judge0CodeRunner


def run_code_job(payload: dict) -> dict:
    """RQ entrypoint for code execution; the API process never waits on Judge0."""
    request = CodeRunRequest.model_validate(payload)
    return Judge0CodeRunner().run(request).model_dump()
