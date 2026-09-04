from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.ai_metrics import AIRequestMetric, ToolCallMetric
from app.services.tool_call_metrics import summarize_tool_call_metrics

router = APIRouter()


@router.get("/summary")
async def metric_summary(db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    base = AIRequestMetric.user_id == current_user.id
    total, failures, latency, hits, prompt, completion, cost = (await db.execute(select(
        func.count(AIRequestMetric.id),
        func.coalesce(func.sum(1 - AIRequestMetric.success), 0),
        func.coalesce(func.avg(AIRequestMetric.latency_ms), 0),
        func.coalesce(func.sum(case((AIRequestMetric.retrieval_count > 0, 1), else_=0)), 0),
        func.coalesce(func.sum(AIRequestMetric.prompt_tokens), 0),
        func.coalesce(func.sum(AIRequestMetric.completion_tokens), 0),
        func.coalesce(func.sum(AIRequestMetric.estimated_cost_usd), 0),
    ).where(base))).one()
    grouped = await db.execute(select(
        AIRequestMetric.operation,
        func.count(AIRequestMetric.id),
        func.coalesce(func.avg(AIRequestMetric.latency_ms), 0),
        func.coalesce(func.avg(AIRequestMetric.model_latency_ms), 0),
        func.coalesce(func.avg(AIRequestMetric.queue_wait_ms), 0),
        func.coalesce(func.sum(AIRequestMetric.prompt_tokens), 0),
        func.coalesce(func.sum(AIRequestMetric.completion_tokens), 0),
        func.coalesce(func.sum(AIRequestMetric.total_tokens), 0),
        func.coalesce(func.sum(AIRequestMetric.cache_hit), 0),
        func.coalesce(func.sum(AIRequestMetric.evidence_retrieval_count), 0),
        func.coalesce(func.sum(AIRequestMetric.evidence_context_chars), 0),
        func.coalesce(func.sum(AIRequestMetric.evidence_cache_hit), 0),
    ).where(base).group_by(AIRequestMetric.operation))
    by_operation = {}
    for operation, count, avg_request, avg_model, avg_queue, prompt_sum, completion_sum, total_sum, cache_hits, evidence_count, evidence_chars, evidence_cache_hits in grouped.all():
        by_operation[operation] = {
            "requests": count,
            "avg_latency_ms": round(avg_request, 1),
            "avg_model_latency_ms": round(avg_model, 1),
            "avg_queue_wait_ms": round(avg_queue, 1),
            "prompt_tokens": prompt_sum,
            "completion_tokens": completion_sum,
            "total_tokens": total_sum,
            "cache_hits": cache_hits,
            "evidence_retrieval_count": evidence_count,
            "evidence_context_chars": evidence_chars,
            "evidence_cache_hits": evidence_cache_hits,
        }
    return {"requests": total, "failure_rate": round(failures / total, 4) if total else 0, "avg_latency_ms": round(latency, 1), "rag_hit_rate": round(hits / total, 3) if total else 0, "prompt_tokens": prompt, "completion_tokens": completion, "estimated_cost_usd": round(cost, 6), "by_operation": by_operation}


@router.get("/tool-calls/summary")
async def tool_call_metric_summary(db: AsyncSession = Depends(get_db), current_user=Depends(get_current_user)):
    result = await db.execute(
        select(ToolCallMetric).where(ToolCallMetric.user_id == current_user.id)
    )
    return summarize_tool_call_metrics(list(result.scalars().all()))
