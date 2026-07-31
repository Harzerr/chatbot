from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.ai_metrics import AIRequestMetric

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
    return {"requests": total, "failure_rate": round(failures / total, 4) if total else 0, "avg_latency_ms": round(latency, 1), "rag_hit_rate": round(hits / total, 3) if total else 0, "prompt_tokens": prompt, "completion_tokens": completion, "estimated_cost_usd": round(cost, 6)}
