import asyncio
import os
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from redis import Redis
from rq import SimpleWorker
from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.datastructures import Headers

from app.api.endpoints.users import (
    retry_resume_parse_job,
    upload_my_resume,
)
from app.core.config import settings
from app.db.base import Base
from app.models.resume import ResumeParseJob, ResumeSource
from app.models.user import User
from app.services import resume_jobs
from app.services import task_queue
from app.services.resume_parser import ParsedPage, ResumeParseResult


class FakeResumeParser:
    mode = "success"
    calls = 0

    async def parse(self, file_path: str, content_type: str) -> ResumeParseResult:
        self.calls += 1
        if self.mode == "failure":
            raise RuntimeError("simulated parser failure")
        return ResumeParseResult(
            text="张三\nPython 后端工程师\n负责简历解析异步任务改造。",
            pages=[ParsedPage(page_number=1, text="张三\nPython 后端工程师")],
            parser_name="test-parser",
            warnings=[],
            quality_score=0.95,
        )


class ResumeQueueIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.redis_url = os.getenv(
            "RESUME_TEST_REDIS_URL",
            "redis://127.0.0.1:6379/15",
        )
        cls.redis = Redis.from_url(cls.redis_url, decode_responses=False)
        try:
            cls.redis.ping()
        except Exception as exc:
            raise RuntimeError(
                f"Redis test database is unavailable: {cls.redis_url}. "
                "Start redis-server or set RESUME_TEST_REDIS_URL."
            ) from exc

        cls.queue_name = f"resume_parse_test_{os.getpid()}"
        cls.original_redis_url = settings.REDIS_URL
        cls.original_queue_name = settings.RESUME_QUEUE_NAME
        settings.REDIS_URL = cls.redis_url
        settings.RESUME_QUEUE_NAME = cls.queue_name

        cls.temp_dir = Path(tempfile.mkdtemp(prefix="resume-queue-test-"))
        cls.database_path = cls.temp_dir / "test.db"
        cls.engine = create_async_engine(
            f"sqlite+aiosqlite:///{cls.database_path}",
            pool_pre_ping=True,
        )
        cls.session_factory = async_sessionmaker(
            bind=cls.engine,
            expire_on_commit=False,
        )
        cls.original_session_factory = resume_jobs.AsyncSessionLocal
        resume_jobs.AsyncSessionLocal = cls.session_factory

        cls.original_parser = resume_jobs.resume_parser
        cls.parser = FakeResumeParser()
        resume_jobs.resume_parser = cls.parser

        asyncio.run(cls._create_schema())
        cls.user_id = asyncio.run(cls._create_user())

    @classmethod
    def tearDownClass(cls):
        cls.redis.delete(f"rq:queue:{cls.queue_name}")
        settings.REDIS_URL = cls.original_redis_url
        settings.RESUME_QUEUE_NAME = cls.original_queue_name
        resume_jobs.AsyncSessionLocal = cls.original_session_factory
        resume_jobs.resume_parser = cls.original_parser
        asyncio.run(cls.engine.dispose())
        for path in sorted(cls.temp_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        cls.temp_dir.rmdir()

    @classmethod
    async def _create_schema(cls):
        async with cls.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)

    @classmethod
    async def _create_user(cls):
        async with cls.session_factory() as db:
            user = User(
                username="resume-queue-test",
                password="not-a-real-password",
                tenant_id="resume-queue-test-tenant",
                full_name="队列测试用户",
                email="resume-queue-test@example.com",
                phone="13800000000",
                target_role="Python 后端工程师",
                years_of_experience=1,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return user.id

    def setUp(self):
        task_queue.get_resume_queue().empty()
        self.parser.mode = "success"
        self.parser.calls = 0

    def _run(self, coroutine):
        return asyncio.run(coroutine)

    def _current_user(self):
        return User(id=self.user_id)

    def _upload_file(self):
        return UploadFile(
            file=BytesIO(b"%PDF-test-resume"),
            filename="test-resume.pdf",
            headers=Headers({"content-type": "application/pdf"}),
        )

    async def _upload(self):
        from app.api.endpoints import users

        original_upload_dir = users.RESUME_UPLOAD_DIR
        users.RESUME_UPLOAD_DIR = self.temp_dir / "uploads"
        try:
            async with self.session_factory() as db:
                return await upload_my_resume(
                    current_user=self._current_user(),
                    db=db,
                    file=self._upload_file(),
                    user_service=None,
                )
        finally:
            users.RESUME_UPLOAD_DIR = original_upload_dir

    async def _get_job(self, job_id):
        async with self.session_factory() as db:
            job = await db.get(ResumeParseJob, job_id)
            source = await db.get(ResumeSource, job.source_id)
            user = await db.get(User, job.user_id)
            return job, source, user

    def _run_worker_once(self):
        queue = task_queue.get_resume_queue()
        worker = SimpleWorker([queue], connection=queue.connection)
        worker.work(burst=True, with_scheduler=False)

    def test_upload_returns_202_and_worker_persists_result(self):
        response = self._run(self._upload())
        self.assertIsNotNone(response.job_id)

        queued_job, queued_source, _ = self._run(self._get_job(response.job_id))
        self.assertEqual(queued_job.status, "queued")
        self.assertEqual(queued_job.executor, "rq")
        self.assertTrue(queued_job.queue_job_id)
        self.assertEqual(queued_source.status, "uploaded")
        self.assertEqual(task_queue.get_resume_queue().count, 1)

        self._run_worker_once()

        completed_job, completed_source, user = self._run(self._get_job(response.job_id))
        self.assertEqual(completed_job.status, "completed")
        self.assertEqual(completed_job.stage, "completed")
        self.assertEqual(completed_job.progress, 100)
        self.assertEqual(completed_job.parser_name, "test-parser")
        self.assertEqual(completed_job.page_count, 1)
        self.assertEqual(completed_source.status, "ready")
        self.assertIn("Python 后端工程师", user.resume_text)
        self.assertEqual(self.parser.calls, 1)

    def test_failed_job_can_be_requeued_and_completed(self):
        self.parser.mode = "failure"
        response = self._run(self._upload())
        self._run_worker_once()

        failed_job, failed_source, _ = self._run(self._get_job(response.job_id))
        self.assertEqual(failed_job.status, "failed")
        self.assertEqual(failed_source.status, "failed")
        self.assertIn("simulated parser failure", failed_job.error_message)

        self.parser.mode = "success"
        async def retry():
            async with self.session_factory() as db:
                return await retry_resume_parse_job(
                    job_id=response.job_id,
                    db=db,
                    current_user=self._current_user(),
                )

        retry_response = self._run(retry())
        self.assertEqual(retry_response.status, "queued")
        self.assertTrue(retry_response.queue_job_id)
        self.assertEqual(task_queue.get_resume_queue().count, 1)

        self._run_worker_once()
        completed_job, completed_source, _ = self._run(self._get_job(response.job_id))
        self.assertEqual(completed_job.status, "completed")
        self.assertEqual(completed_source.status, "ready")

    def test_backend_recovery_requeues_processing_job(self):
        response = self._run(self._upload())
        task_queue.get_resume_queue().empty()

        async def mark_processing():
            async with self.session_factory() as db:
                job = await db.get(ResumeParseJob, response.job_id)
                source = await db.get(ResumeSource, job.source_id)
                job.status = "processing"
                job.stage = "extracting_text"
                source.status = "processing"
                await db.commit()

        self._run(mark_processing())
        self._run(resume_jobs.recover_pending_resume_parse_jobs())

        recovered_job, recovered_source, _ = self._run(self._get_job(response.job_id))
        self.assertEqual(recovered_job.status, "queued")
        self.assertEqual(recovered_job.stage, "queued")
        self.assertEqual(recovered_source.status, "processing")
        self.assertTrue(recovered_job.queue_job_id)
        self.assertEqual(task_queue.get_resume_queue().count, 1)

        self._run_worker_once()
        completed_job, completed_source, _ = self._run(self._get_job(response.job_id))
        self.assertEqual(completed_job.status, "completed")
        self.assertEqual(completed_source.status, "ready")

    def test_queue_unavailable_marks_upload_failed(self):
        from app.api.endpoints import users

        original_upload_dir = users.RESUME_UPLOAD_DIR
        users.RESUME_UPLOAD_DIR = self.temp_dir / "unavailable-uploads"
        try:
            with patch(
                "app.api.endpoints.users.enqueue_resume_parse_job",
                side_effect=task_queue.QueueUnavailable("simulated Redis outage"),
            ):
                async def upload_with_unavailable_queue():
                    async with self.session_factory() as db:
                        with self.assertRaises(HTTPException) as context:
                            await upload_my_resume(
                                current_user=self._current_user(),
                                db=db,
                                file=self._upload_file(),
                                user_service=None,
                            )
                        return context.exception

                error = self._run(upload_with_unavailable_queue())
        finally:
            users.RESUME_UPLOAD_DIR = original_upload_dir

        self.assertEqual(error.status_code, 503)

        async def latest_job():
            async with self.session_factory() as db:
                job = (
                    await db.execute(
                        select(ResumeParseJob)
                        .where(ResumeParseJob.user_id == self.user_id)
                        .order_by(ResumeParseJob.id.desc())
                    )
                ).scalars().first()
                source = await db.get(ResumeSource, job.source_id)
                return job, source

        job, source = self._run(latest_job())
        self.assertEqual(job.status, "failed")
        self.assertEqual(source.status, "failed")
        self.assertEqual(job.error_message, "解析队列不可用，请稍后重试")

    def test_enqueue_reports_redis_unavailable(self):
        with patch(
            "app.services.task_queue.get_resume_queue",
            side_effect=task_queue.QueueUnavailable("simulated Redis outage"),
        ):
            with self.assertRaises(task_queue.QueueUnavailable):
                task_queue.enqueue_resume_parse_job(999999)


if __name__ == "__main__":
    unittest.main(verbosity=2)
