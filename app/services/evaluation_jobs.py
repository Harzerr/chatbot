import asyncio
import time

from rq import get_current_job

from app.agent.evaluation_agent import EvaluationAgent
from app.schemas.evaluation import EvaluationRequest
from app.services.vector_store import MultiTenantVectorStore
from app.services.evaluation_cache import get_cached_evaluation, set_cached_evaluation, evaluation_cache_key
from app.services.redis_cache import RedisCache
from app.services.career_knowledge import evidence_context_stats
from app.services.metrics import record_ai_metric
from app.core.config import settings
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


async def process_evaluation_job(payload: dict) -> dict:
    point_id = str(payload["point_id"])
    tenant_id = str(payload["tenant_id"])
    user_id = str(payload["user_id"])
    chat_id = str(payload["chat_id"])
    current_job = get_current_job()
    job_id = payload.get("job_id") or (current_job.id if current_job else None)
    force_refresh = bool(payload.get("force_refresh"))
    vector_store = None
    queued_at = float(payload.get("queued_at") or 0)

    async def record_evaluation_metric(
        *,
        result: dict,
        latency_ms: float,
        queue_wait_ms: float,
        cache_hit: bool = False,
        success: int = 1,
    ) -> None:
        evidence_stats = evidence_context_stats(str(result.get("knowledge_context") or payload.get("request", {}).get("knowledge_context") or ""))
        await record_ai_metric(
            user_id=int(user_id),
            tenant_id=tenant_id,
            operation="interview_evaluation",
            model=settings.EVALUATION_LLM_MODEL,
            success=success,
            latency_ms=latency_ms,
            model_latency_ms=float(result.get("evaluation_model_latency_ms") or 0),
            queue_wait_ms=queue_wait_ms,
            retrieval_count=0,
            evidence_retrieval_count=evidence_stats["retrieval_count"],
            evidence_context_chars=evidence_stats["context_chars"],
            evidence_cache_hit=int(payload.get("request", {}).get("knowledge_context_cache_hit", False)),
            evidence_retrieval_method=evidence_stats["retrieval_method"],
            prompt_tokens=int(result.get("evaluation_prompt_tokens") or 0),
            completion_tokens=int(result.get("evaluation_completion_tokens") or 0),
            total_tokens=int(result.get("evaluation_total_tokens") or 0),
            cache_hit=int(cache_hit),
            attempt=int(result.get("evaluation_attempts") or 0),
            estimated_cost_usd=0,
        )

    def persist_completed(result: dict) -> None:
        vector_store.update_conversation_evaluation(
            point_id=point_id,
            tenant_id=tenant_id,
            user_id=user_id,
            chat_id=chat_id,
            status="completed",
            evaluation=result,
            job_id=job_id,
        )

    try:
        vector_store = MultiTenantVectorStore()
        vector_store.update_conversation_evaluation(
            point_id=point_id,
            tenant_id=tenant_id,
            user_id=user_id,
            chat_id=chat_id,
            status="processing",
            job_id=job_id,
        )
        request = EvaluationRequest.model_validate(payload["request"])
        cache = RedisCache()
        cache_key = evaluation_cache_key(request)
        if force_refresh:
            cache.delete(cache_key)
        cached_result = None if force_refresh else get_cached_evaluation(request, cache)
        if cached_result is not None:
            cached_result["evaluation_cache_hit"] = True
            persist_completed(cached_result)
            await record_evaluation_metric(
                result=cached_result,
                latency_ms=0,
                queue_wait_ms=max(0, (time.time() - queued_at) * 1000) if queued_at else 0,
                cache_hit=True,
            )
            logger.info("Interview evaluation cache hit: chat_id=%s point_id=%s", chat_id, point_id)
            return cached_result

        lock_key = f"{cache_key}:lock"
        lock_ttl = getattr(settings, "EVALUATION_LOCK_TTL_SECONDS", 60)
        lock_token = cache.acquire_lock(lock_key, lock_ttl)
        if lock_token is None and cache.available is True:
            # Another worker owns the same request. Wait for its result instead of
            # issuing a duplicate model call; the lock TTL bounds this wait.
            deadline = time.monotonic() + lock_ttl
            while time.monotonic() < deadline:
                await asyncio.sleep(0.5)
                cached_result = get_cached_evaluation(request, cache)
                if cached_result is not None:
                    cached_result["evaluation_cache_hit"] = True
                    persist_completed(cached_result)
                    await record_evaluation_metric(
                        result=cached_result,
                        latency_ms=0,
                        queue_wait_ms=max(0, (time.time() - queued_at) * 1000) if queued_at else 0,
                        cache_hit=True,
                    )
                    logger.info("Interview evaluation singleflight hit: chat_id=%s point_id=%s", chat_id, point_id)
                    return cached_result
            lock_token = cache.acquire_lock(lock_key, lock_ttl)

        try:
            # Recheck after acquiring the lock because the owner may have finished
            # between the initial cache read and lock acquisition.
            cached_result = None if force_refresh else get_cached_evaluation(request, cache)
            if cached_result is not None:
                cached_result["evaluation_cache_hit"] = True
                persist_completed(cached_result)
                await record_evaluation_metric(
                    result=cached_result,
                    latency_ms=0,
                    queue_wait_ms=max(0, (time.time() - queued_at) * 1000) if queued_at else 0,
                    cache_hit=True,
                )
                return cached_result

            evaluation_started_at = time.perf_counter()
            evaluation = await EvaluationAgent().evaluate(request)
            result = evaluation.model_dump()
            set_cached_evaluation(request, result, cache)
            persist_completed(result)
            await record_evaluation_metric(
                result=result,
                latency_ms=(time.perf_counter() - evaluation_started_at) * 1000,
                queue_wait_ms=max(0, (time.time() - queued_at) * 1000) if queued_at else 0,
            )
        finally:
            if lock_token:
                cache.release_lock(lock_key, lock_token)
        logger.info(
            "Interview evaluation completed: chat_id=%s point_id=%s latency_ms=%s",
            chat_id,
            point_id,
            result.get("evaluation_latency_ms", 0),
        )
        return result
    except Exception as exc:
        logger.exception("Interview evaluation failed: chat_id=%s point_id=%s", chat_id, point_id)
        try:
            if vector_store is not None:
                vector_store.update_conversation_evaluation(
                    point_id=point_id,
                    tenant_id=tenant_id,
                    user_id=user_id,
                    chat_id=chat_id,
                    status="failed",
                    job_id=job_id,
                    error_message=str(exc),
                )
        except Exception:
            logger.exception("Failed to persist interview evaluation failure: chat_id=%s", chat_id)
        raise


def run_evaluation_job(payload: dict) -> dict:
    """RQ entrypoint for non-blocking interview answer evaluation."""
    return asyncio.run(process_evaluation_job(payload))
