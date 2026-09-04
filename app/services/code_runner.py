from __future__ import annotations

import hashlib
import json
import time
from typing import Any

import requests
from fastapi import HTTPException, status
from redis.exceptions import RedisError

from app.core.config import settings
from app.schemas.api import CodeRunRequest, CodeRunResponse
from app.services.task_queue import get_redis_connection


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

    @staticmethod
    def _cache_key(request: CodeRunRequest) -> str:
        payload = json.dumps(
            {
                "language": request.language,
                "source_code": request.source_code,
                "stdin": request.stdin or "",
                "expected_output": request.expected_output,
            },
            ensure_ascii=False,
            sort_keys=True,
        ).encode("utf-8")
        return f"code-runner:v1:{hashlib.sha256(payload).hexdigest()}"

    def _read_cached(self, request: CodeRunRequest) -> CodeRunResponse | None:
        try:
            cached = get_redis_connection().get(self._cache_key(request))
            if cached:
                return CodeRunResponse.model_validate_json(cached)
        except (RedisError, ValueError, TypeError):
            pass
        return None

    def _write_cached(self, request: CodeRunRequest, response: CodeRunResponse) -> None:
        try:
            get_redis_connection().setex(
                self._cache_key(request),
                settings.JUDGE0_CACHE_TTL_SECONDS,
                response.model_dump_json(),
            )
        except RedisError:
            pass

    def run(self, request: CodeRunRequest) -> CodeRunResponse:
        cached = self._read_cached(request)
        if cached:
            return cached

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
            if request.language == "java":
                # Java VM needs larger virtual address space for metaspace reservation under isolate.
                payload["memory_limit"] = settings.JUDGE0_JAVA_MEMORY_LIMIT_KB
            elif request.language in {"javascript", "typescript"}:
                payload["memory_limit"] = settings.JUDGE0_WINDOWS_MEMORY_LIMIT_KB

        try:
            response = requests.post(
                f"{self.base_url}/submissions?wait=false",
                json=payload,
                headers=headers,
                timeout=min(self.timeout, 8.0),
            )
            response.raise_for_status()
            token = response.json().get("token")
            if not token:
                raise RuntimeError("Judge0 did not return a submission token")
        except requests.Timeout as exc:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Judge0 submission timed out",
            ) from exc
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Judge0 request failed: {exc}",
            ) from exc

        deadline = time.monotonic() + self.timeout
        body: dict[str, Any] = {}
        while time.monotonic() < deadline:
            try:
                result_response = requests.get(
                    f"{self.base_url}/submissions/{token}?base64_encoded=false",
                    headers=headers,
                    timeout=min(self.timeout, 5.0),
                )
                result_response.raise_for_status()
                body = result_response.json()
            except requests.Timeout:
                body = {}
            except requests.RequestException as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Judge0 polling failed: {exc}",
                ) from exc

            status_id = (body.get("status") or {}).get("id")
            if status_id not in {1, 2, None}:
                break
            time.sleep(settings.JUDGE0_POLL_INTERVAL)
        else:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Judge0 execution timed out",
            )

        stdout = body.get("stdout") or ""
        stderr = body.get("stderr") or ""
        compile_output = body.get("compile_output") or ""
        message = body.get("message") or ""

        passed = None
        if request.expected_output is not None:
            passed = stdout.strip() == request.expected_output.strip()

        result = CodeRunResponse(
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
        self._write_cached(request, result)
        return result
