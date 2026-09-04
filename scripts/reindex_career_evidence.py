#!/usr/bin/env python
"""Queue a full rebuild of the career-document vector index.

Run after enabling CAREER_EVIDENCE_VECTOR_ENABLED=true in .env.
"""

import asyncio

from sqlalchemy import select

from app.core.config import settings
from app.db.session import AsyncSessionLocal
from app.models.career import CareerKnowledgeDocument
from app.models.user import User
from app.services.task_queue import QueueUnavailable, enqueue_career_evidence_index_job


async def main() -> None:
    if not settings.CAREER_EVIDENCE_VECTOR_ENABLED:
        raise SystemExit("请先在 .env 设置 CAREER_EVIDENCE_VECTOR_ENABLED=true")
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(CareerKnowledgeDocument.id, CareerKnowledgeDocument.user_id, User.tenant_id)
            .join(User, User.id == CareerKnowledgeDocument.user_id)
            .where(CareerKnowledgeDocument.is_archived.is_(False))
        )
        rows = result.all()
    queued = 0
    for document_id, user_id, tenant_id in rows:
        try:
            enqueue_career_evidence_index_job({
                "document_id": document_id,
                "user_id": user_id,
                "tenant_id": tenant_id,
            })
            queued += 1
        except QueueUnavailable as exc:
            raise SystemExit(f"索引队列不可用：{exc}") from exc
    print(f"已提交 {queued} 个职业技术文档索引任务")


if __name__ == "__main__":
    asyncio.run(main())
