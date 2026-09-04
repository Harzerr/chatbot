import asyncio
import json

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.db.session import AsyncSessionLocal
from app.models.career import CareerFact, CareerKnowledgeChunk, CareerKnowledgeDocument
from app.models.user import User
from app.services.career_evidence_vector_store import CareerEvidenceVectorStore
from app.services.career_knowledge import (
    CLAIM_LINKING_VERSION,
    build_knowledge_document_chunks,
    link_claims_to_chunks,
    project_claims_for_document,
)
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


async def process_career_evidence_index_job(payload: dict) -> dict:
    from app.core.config import settings

    document_id = int(payload["document_id"])
    user_id = int(payload["user_id"])
    tenant_id = str(payload["tenant_id"])
    async with AsyncSessionLocal() as db:
        row = await db.execute(
            select(CareerKnowledgeDocument, User)
            .join(User, User.id == CareerKnowledgeDocument.user_id)
            .options(selectinload(CareerKnowledgeDocument.chunks))
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

        if not document.is_archived:
            try:
                document_metadata = json.loads(document.metadata_json or "{}")
            except (TypeError, json.JSONDecodeError):
                document_metadata = {}
            needs_claim_rebuild = (
                not document.chunks
                or document_metadata.get("claim_linking_version") != CLAIM_LINKING_VERSION
            )
        else:
            document_metadata = {}
            needs_claim_rebuild = False

        if needs_claim_rebuild:
            fact = None
            if document.fact_id:
                fact = await db.scalar(
                    select(CareerFact).where(
                        CareerFact.id == document.fact_id,
                        CareerFact.user_id == document.user_id,
                    )
                )
            project_key = str(document_metadata.get("project_key") or "").strip()
            try:
                fact_content = json.loads(fact.content_json or "{}") if fact else {}
            except (TypeError, json.JSONDecodeError):
                fact_content = {}
            claims = project_claims_for_document(
                fact_content,
                fact.title if fact else document.title,
                project_key or None,
            )
            chunks = link_claims_to_chunks(build_knowledge_document_chunks(
                document,
                max_chunk_chars=settings.EVIDENCE_CHUNK_MAX_CHARS,
                overlap_chars=settings.EVIDENCE_CHUNK_OVERLAP_CHARS,
            ), claims)
            db.add_all(
                [
                    CareerKnowledgeChunk(
                        document_id=document.id,
                        user_id=document.user_id,
                        fact_id=document.fact_id,
                        chunk_index=chunk["chunk_index"],
                        chunk_id=str(chunk["chunk_id"]),
                        section=str(chunk["section"])[:255],
                        text=str(chunk["text"]),
                        project_key=str(chunk.get("project_key") or project_key)[:128],
                        claim_ids_json=json.dumps(chunk.get("claim_ids", []), ensure_ascii=False),
                        claim_texts_json=json.dumps(chunk.get("claim_texts", []), ensure_ascii=False),
                        source_version=chunk.get("source_version"),
                        chunking_version=str(chunk["chunking_version"]),
                    )
                    for chunk in chunks
                ]
            )
            document_metadata.update({
                "project_key": project_key,
                "claim_linking_version": CLAIM_LINKING_VERSION,
            })
            document.metadata_json = json.dumps(document_metadata, ensure_ascii=False)
            await db.commit()
            await db.refresh(document, ["chunks"])

        if not getattr(settings, "CAREER_EVIDENCE_VECTOR_ENABLED", False):
            return {"status": "chunks_persisted", "document_id": document_id, "indexed_chunks": 0}

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
