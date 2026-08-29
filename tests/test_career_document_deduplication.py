import asyncio
import json
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException, Response, UploadFile
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import Headers

from app.api.endpoints.career import upload_knowledge_document
from app.db.base import Base
from app.db.bootstrap import ensure_career_knowledge_columns
from app.models.career import CareerFact, CareerKnowledgeDocument
from app.models.user import User


class CareerDocumentDeduplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory(prefix="career-document-dedup-")
        database_path = Path(self.temp_dir.name) / "test.db"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}")
        self.session_factory = async_sessionmaker(bind=self.engine, expire_on_commit=False)
        self.user_id, self.first_fact_id, self.second_fact_id = asyncio.run(self._seed_database())

    def tearDown(self):
        asyncio.run(self.engine.dispose())
        self.temp_dir.cleanup()

    async def _seed_database(self) -> tuple[int, int, int]:
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        async with self.session_factory() as db:
            user = User(
                username="career-document-dedup",
                password="not-a-real-password",
                tenant_id="tenant-dedup",
                full_name="测试用户",
                email="career-document-dedup@example.com",
                phone="13800000000",
                target_role="后端工程师",
                years_of_experience=1,
            )
            db.add(user)
            await db.flush()
            first_fact = CareerFact(
                user_id=user.id,
                fact_type="project",
                title="项目 A",
                content_json=json.dumps({"title": "项目 A"}, ensure_ascii=False),
                tags_json="[]",
            )
            second_fact = CareerFact(
                user_id=user.id,
                fact_type="project",
                title="项目 B",
                content_json=json.dumps({"title": "项目 B"}, ensure_ascii=False),
                tags_json="[]",
            )
            db.add_all([first_fact, second_fact])
            await db.commit()
            return user.id, first_fact.id, second_fact.id

    @staticmethod
    def _file(content: bytes = b"# RQ Worker\n\nRedis + RQ async evaluation pipeline.") -> UploadFile:
        return UploadFile(
            file=BytesIO(content),
            filename="project.md",
            headers=Headers({"content-type": "text/markdown"}),
        )

    def _run(self, coroutine):
        return asyncio.run(coroutine)

    async def _upload(self, fact_id: int, content: bytes | None = None):
        async with self.session_factory() as db:
            user = await db.get(User, self.user_id)
            with patch(
                "app.api.endpoints.career._enqueue_career_evidence_index",
                new_callable=AsyncMock,
            ):
                return await upload_knowledge_document(
                    response=Response(),
                    file=self._file(content or b"# RQ Worker\n\nRedis + RQ async evaluation pipeline."),
                    fact_id=fact_id,
                    title=None,
                    project_key=None,
                    db=db,
                    current_user=user,
                )

    async def _document_counts(self) -> tuple[int, int]:
        async with self.session_factory() as db:
            total = await db.scalar(select(func.count()).select_from(CareerKnowledgeDocument))
            active = await db.scalar(
                select(func.count()).select_from(CareerKnowledgeDocument).where(
                    CareerKnowledgeDocument.is_archived.is_(False)
                )
            )
            return int(total or 0), int(active or 0)

    def test_repeated_upload_for_same_fact_reuses_existing_document(self):
        created = self._run(self._upload(self.first_fact_id))
        duplicate = self._run(self._upload(self.first_fact_id))

        self.assertEqual(duplicate.id, created.id)
        self.assertTrue(duplicate.deduplicated)
        self.assertFalse(duplicate.restored_from_archive)
        self.assertEqual(self._run(self._document_counts()), (1, 1))

    def test_same_source_cannot_be_silently_bound_to_another_fact(self):
        self._run(self._upload(self.first_fact_id))

        with self.assertRaises(HTTPException) as context:
            self._run(self._upload(self.second_fact_id))

        self.assertEqual(context.exception.status_code, 409)
        self.assertIn("已绑定到另一个项目", context.exception.detail)
        self.assertEqual(self._run(self._document_counts()), (1, 1))

    def test_reupload_restores_archived_document_instead_of_creating_a_copy(self):
        created = self._run(self._upload(self.first_fact_id))

        async def archive_document():
            async with self.session_factory() as db:
                document = await db.get(CareerKnowledgeDocument, created.id)
                document.is_archived = True
                await db.commit()

        self._run(archive_document())
        restored = self._run(self._upload(self.first_fact_id))

        self.assertEqual(restored.id, created.id)
        self.assertTrue(restored.deduplicated)
        self.assertTrue(restored.restored_from_archive)
        self.assertEqual(self._run(self._document_counts()), (1, 1))

    def test_database_constraint_blocks_concurrent_active_duplicates(self):
        created = self._run(self._upload(self.first_fact_id))

        async def insert_duplicate():
            async with self.session_factory() as db:
                db.add(CareerKnowledgeDocument(
                    user_id=self.user_id,
                    fact_id=self.first_fact_id,
                    title="并发副本",
                    file_name="duplicate.md",
                    document_type="technical_doc",
                    content_type="text/markdown",
                    content_text=created.content_text,
                    metadata_json="{}",
                    source_hash=created.source_hash,
                ))
                await db.commit()

        with self.assertRaises(IntegrityError):
            self._run(insert_duplicate())
        self.assertEqual(self._run(self._document_counts()), (1, 1))

    def test_bootstrap_archives_historical_duplicates_before_creating_index(self):
        created = self._run(self._upload(self.first_fact_id))

        async def create_legacy_duplicate_and_migrate():
            async with self.engine.begin() as connection:
                await connection.execute(text("DROP INDEX uq_career_knowledge_documents_active_source"))
                await connection.execute(text("""
                    INSERT INTO career_knowledge_documents (
                        user_id, fact_id, title, file_name, document_type, content_type,
                        content_text, metadata_json, source_hash, is_archived, created_at, updated_at
                    ) VALUES (
                        :user_id, :fact_id, '历史副本', 'legacy.md', 'technical_doc', 'text/markdown',
                        :content_text, '{}', :source_hash, 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                """), {
                    "user_id": self.user_id,
                    "fact_id": self.first_fact_id,
                    "content_text": created.content_text,
                    "source_hash": created.source_hash,
                })
            await ensure_career_knowledge_columns(self.engine)

        self._run(create_legacy_duplicate_and_migrate())
        self.assertEqual(self._run(self._document_counts()), (2, 1))


if __name__ == "__main__":
    unittest.main()
