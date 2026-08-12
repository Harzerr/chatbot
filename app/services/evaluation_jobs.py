import asyncio

from rq import get_current_job

from app.agent.evaluation_agent import EvaluationAgent
from app.schemas.evaluation import EvaluationRequest
from app.services.vector_store import MultiTenantVectorStore
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


async def process_evaluation_job(payload: dict) -> dict:
    point_id = str(payload["point_id"])
    tenant_id = str(payload["tenant_id"])
    user_id = str(payload["user_id"])
    chat_id = str(payload["chat_id"])
    current_job = get_current_job()
    job_id = payload.get("job_id") or (current_job.id if current_job else None)
    vector_store = MultiTenantVectorStore()

    vector_store.update_conversation_evaluation(
        point_id=point_id,
        tenant_id=tenant_id,
        user_id=user_id,
        chat_id=chat_id,
        status="processing",
        job_id=job_id,
    )

    try:
        request = EvaluationRequest.model_validate(payload["request"])
        evaluation = await EvaluationAgent().evaluate(request)
        result = evaluation.model_dump()
        vector_store.update_conversation_evaluation(
            point_id=point_id,
            tenant_id=tenant_id,
            user_id=user_id,
            chat_id=chat_id,
            status="completed",
            evaluation=result,
            job_id=job_id,
        )
        logger.info(
            "Interview evaluation completed: chat_id=%s point_id=%s latency_ms=%s",
            chat_id,
            point_id,
            evaluation.evaluation_latency_ms,
        )
        return result
    except Exception as exc:
        logger.exception("Interview evaluation failed: chat_id=%s point_id=%s", chat_id, point_id)
        try:
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
