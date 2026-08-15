import asyncio

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.career import CareerKnowledgeDocument
from app.models.user import User
from app.services.career_evidence_vector_store import CareerEvidenceVectorStore
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


async def process_career_evidence_index_job(payload: dict) -> dict:
    from app.core.config import settings

    if not getattr(settings, "CAREER_EVIDENCE_VECTOR_ENABLED", False):
        return {"status": "disabled", "document_id": payload.get("document_id"), "indexed_chunks": 0}
    document_id = int(payload["document_id"])
    user_id = int(payload["user_id"])
    tenant_id = str(payload["tenant_id"])
    async with AsyncSessionLocal() as db:
        row = await db.execute(
            select(CareerKnowledgeDocument, User)
            .join(User, User.id == CareerKnowledgeDocument.user_id)
            .where(
                CareerKnowledgeDocument.id == document_id,
                CareerKnowledgeDocument.user_id == user_id,
                User.tenant_id == tenant_id,
            )
        )
        result = row.one_or_none()
        if not result:
            logger.info("Career evidence document was deleted before indexing: document_id=%s", document_id)
            return {"status": "deleted", "document_id": document_id}
        document, _ = result

    vector_store = CareerEvidenceVectorStore()
    if document.is_archived:
        vector_store.delete_document(
            tenant_id=tenant_id,
            user_id=str(user_id),
            document_id=str(document_id),
        )
        return {"status": "archived", "document_id": document_id, "indexed_chunks": 0}

    indexed_chunks = vector_store.upsert_document(
        document=document,
        tenant_id=tenant_id,
        user_id=str(user_id),
    )
    logger.info("Career evidence indexed: document_id=%s chunks=%s", document_id, indexed_chunks)
    return {"status": "indexed", "document_id": document_id, "indexed_chunks": indexed_chunks}


def run_career_evidence_index_job(payload: dict) -> dict:
    return asyncio.run(process_career_evidence_index_job(payload))
