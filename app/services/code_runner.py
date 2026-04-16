from __future__ import annotations

from typing import Any

import requests
from fastapi import HTTPException, status

from app.core.config import settings
from app.schemas.api import CodeRunRequest, CodeRunResponse


LANGUAGE_ID_MAP = {
    "cpp": 54,
    "java": 62,
    "python": 71,
    "javascript": 63,
    "typescript": 74,
}


class Judge0CodeRunner:
    def __init__(self) -> None:
        self.base_url = settings.JUDGE0_API_URL.rstrip("/")
        self.timeout = settings.JUDGE0_TIMEOUT
        self.api_key = settings.JUDGE0_API_KEY

    def run(self, request: CodeRunRequest) -> CodeRunResponse:
        language_id = LANGUAGE_ID_MAP.get(request.language)
        if not language_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported language: {request.language}",
            )

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-Auth-Token"] = self.api_key

        payload: dict[str, Any] = {
            "language_id": language_id,
            "source_code": request.source_code,
            "stdin": request.stdin or "",
        }

        if settings.JUDGE0_WINDOWS_COMPAT_MODE:
            payload["enable_per_process_and_thread_time_limit"] = True
            payload["enable_per_process_and_thread_memory_limit"] = True
            if request.language in {"javascript", "typescript"}:
                payload["memory_limit"] = settings.JUDGE0_WINDOWS_MEMORY_LIMIT_KB

        try:
            response = requests.post(
                f"{self.base_url}/submissions?wait=true",
                json=payload,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
        except requests.Timeout as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Judge0 execution timed out",
            ) from exc
        except requests.RequestException as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Judge0 request failed: {exc}",
            ) from exc

        body = response.json()
        stdout = body.get("stdout") or ""
        stderr = body.get("stderr") or ""
        compile_output = body.get("compile_output") or ""
        message = body.get("message") or ""

        passed = None
        if request.expected_output is not None:
            passed = stdout.strip() == request.expected_output.strip()

        return CodeRunResponse(
            status=(body.get("status") or {}).get("description", "Unknown"),
            stdout=stdout,
            stderr=stderr,
            compile_output=compile_output,
            message=message,
            time=body.get("time"),
            memory=body.get("memory"),
            token=body.get("token"),
            passed=passed,
        )
