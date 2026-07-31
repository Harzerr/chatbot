from app.db.session import AsyncSessionLocal
from app.models.ai_metrics import AIRequestMetric


async def record_ai_metric(**values) -> None:
    try:
        async with AsyncSessionLocal() as session:
            session.add(AIRequestMetric(**values))
            await session.commit()
    except Exception:
        # Observability must never make an interview request fail.
        return
