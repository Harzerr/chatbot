"""Backfill canonical chunks for career knowledge documents."""

import argparse
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.bootstrap import ensure_career_knowledge_columns
from app.db.session import AsyncSessionLocal, async_engine
from app.models.career import CareerFact, CareerKnowledgeChunk, CareerKnowledgeDocument
from app.services.career_knowledge import (
    CLAIM_LINKING_VERSION,
    build_knowledge_document_chunks,
    link_claims_to_chunks,
    project_claims_for_document,
)


async def backfill(document_id: int | None = None) -> int:
    await ensure_career_knowledge_columns(async_engine)
    query = select(CareerKnowledgeDocument).options(selectinload(CareerKnowledgeDocument.chunks))
    if document_id is not None:
        query = query.where(CareerKnowledgeDocument.id == document_id)

    total = 0
    async with AsyncSessionLocal() as db:
        documents = (await db.scalars(query.order_by(CareerKnowledgeDocument.id))).all()
        for document in documents:
            fact = None
            if document.fact_id:
                fact = await db.scalar(
                    select(CareerFact).where(
                        CareerFact.id == document.fact_id,
                        CareerFact.user_id == document.user_id,
                    )
                )
            try:
                metadata = json.loads(document.metadata_json or "{}")
            except json.JSONDecodeError:
                metadata = {}
            project_key = str(metadata.get("project_key") or "").strip()
            try:
                fact_content = json.loads(fact.content_json or "{}") if fact else {}
            except json.JSONDecodeError:
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
            metadata.update({
                "project_key": project_key,
                "claim_linking_version": CLAIM_LINKING_VERSION,
            })
            document.metadata_json = json.dumps(metadata, ensure_ascii=False)
            await db.execute(
                delete(CareerKnowledgeChunk).where(CareerKnowledgeChunk.document_id == document.id)
            )
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
            total += len(chunks)
        await db.commit()
    await async_engine.dispose()
    return total


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-id", type=int, default=None)
    args = parser.parse_args()
    print(f"backfilled_chunks={asyncio.run(backfill(args.document_id))}")


if __name__ == "__main__":
    main()
