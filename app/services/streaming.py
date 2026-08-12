import asyncio
import json
import traceback
from time import perf_counter

from typing import AsyncGenerator

from fastapi.responses import StreamingResponse
from fastapi import HTTPException

from app.agent.chat_agent import AISupport
from app.models.user import User
from app.schemas.api import LLMRequest
from app.utils.logger import setup_logger
from app.utils.openai_mapper import create_streaming_openai_chunk
from app.services.metrics import record_ai_metric

logger = setup_logger(__name__)


class StreamingService:
    _instance = None

    def __new__(cls, support_agent: AISupport):
        if cls._instance is None:
            cls._instance = super(StreamingService, cls).__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self, support_agent: AISupport):
        if self._initialized:
            return
        self.support_agent = support_agent
        self._initialized = True

    async def streaming_chat(self, request: LLMRequest, current_user: User) -> StreamingResponse:
        try:
            async def generate_stream() -> AsyncGenerator[str, None]:
                started_at = perf_counter()
                first_chunk = await create_streaming_openai_chunk(role="assistant")
                yield f"data: {json.dumps(first_chunk)}\n\n"

                content_queue: asyncio.Queue[str | Exception | None] = asyncio.Queue()
                streamed_any = False
                streamed_content = ""

                async def publish_chunk(content: str) -> None:
                    nonlocal streamed_any, streamed_content
                    streamed_any = True
                    streamed_content += content
                    await content_queue.put(content)

                interview_mode = bool(
                    request.skill_name == "interview-skills"
                    or request.interview_role
                    or request.interview_level
                    or request.interview_type
                )

                async def run_request() -> None:
                    nonlocal streamed_content
                    try:
                        kwargs = {
                            "question": request.user_message,
                            "user_id": str(current_user.id),
                            "chat_id": request.chat_id,
                            "tenant_id": current_user.tenant_id,
                            "skill_name": request.skill_name,
                            "interview_role": request.interview_role,
                            "interview_level": request.interview_level,
                            "interview_type": request.interview_type,
                            "target_company": request.target_company,
                            "jd_content": request.jd_content,
                            "resume_content": request.resume_content,
                            "code_execution": request.code_execution.model_dump() if request.code_execution else None,
                            "knowledge_context": request.knowledge_context,
                        }
                        if interview_mode:
                            response = await self.support_agent.ask_stream(
                                on_chunk=publish_chunk,
                                **kwargs,
                            )
                        else:
                            response = await self.support_agent.ask(**kwargs)
                        if interview_mode and response.get("messages"):
                            full_response = str(response["messages"][0] or "")
                            if full_response != streamed_content:
                                if full_response.startswith(streamed_content):
                                    missing_suffix = full_response[len(streamed_content):]
                                    if missing_suffix:
                                        await content_queue.put(missing_suffix)
                                        streamed_content += missing_suffix
                                elif not streamed_any:
                                    await content_queue.put(full_response)
                                else:
                                    logger.warning(
                                        "Interview stream content mismatch; keeping streamed response to avoid duplication chat_id=%s",
                                        request.chat_id,
                                    )
                        if response.get("messages") and (not interview_mode or not streamed_any):
                            await content_queue.put(response["messages"][0])
                    except Exception as exc:
                        await content_queue.put(exc)
                    finally:
                        await content_queue.put(None)

                request_task = asyncio.create_task(run_request())

                try:
                    while True:
                        content = await content_queue.get()
                        if content is None:
                            break
                        if isinstance(content, Exception):
                            await record_ai_metric(user_id=current_user.id, tenant_id=current_user.tenant_id, operation="interview" if interview_mode else "chat", model=None, success=0, latency_ms=(perf_counter() - started_at) * 1000, retrieval_count=0)
                            raise content
                        chunk_data = await create_streaming_openai_chunk(content=content)
                        yield f"data: {json.dumps(chunk_data)}\n\n"
                finally:
                    if not request_task.done():
                        request_task.cancel()

                final_chunk = await create_streaming_openai_chunk(finish_reason="stop")
                yield f"data: {json.dumps(final_chunk)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                generate_stream(),
                media_type="text/event-stream",
                headers={
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                    "Content-Encoding": "identity",
                    "X-Accel-Buffering": "no",
                }
            )
        except Exception as e:
            logger.error(f"Error in chat_completions: {str(e)}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            raise HTTPException(status_code=500, detail=str(e))
