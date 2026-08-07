import asyncio
import json
from datetime import datetime

from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.models.resume import ResumeParseJob, ResumeSource
from app.models.user import User
from app.services.resume_parser import ResumeParserService
from app.utils.logger import setup_logger

logger = setup_logger(__name__)
resume_parser = ResumeParserService()


async def process_resume_parse_job(job_id: int) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ResumeParseJob, ResumeSource, User)
            .join(ResumeSource, ResumeSource.id == ResumeParseJob.source_id)
            .join(User, User.id == ResumeParseJob.user_id)
            .where(ResumeParseJob.id == job_id)
        )
        row = result.one_or_none()
        if not row:
            logger.warning("Resume parse job %s was not found", job_id)
            return

        job, source, user = row
        if job.status not in {"queued", "processing"}:
            return

        job.status = "processing"
        job.stage = "extracting_text"
        job.progress = 10
        job.started_at = job.started_at or datetime.utcnow()
        source.status = "processing"
        await db.commit()

        try:
            result = await resume_parser.parse(source.stored_path, source.content_type)
            job.extracted_text = result.text
            job.parser_name = result.parser_name
            job.page_count = len(result.pages)
            job.quality_score = result.quality_score
            job.warnings_json = json.dumps(result.warnings, ensure_ascii=False)
            job.status = "completed"
            job.stage = "completed"
            job.progress = 100
            job.finished_at = datetime.utcnow()
            source.status = "ready"

            user.resume_file_name = source.original_filename
            user.resume_file_path = source.stored_path
            user.resume_content_type = source.content_type
            user.resume_uploaded_at = source.created_at.isoformat()
            user.resume_text = result.text
            await db.commit()
            logger.info(
                "Resume parse job completed: job_id=%s parser=%s pages=%s quality=%s",
                job_id,
                result.parser_name,
                len(result.pages),
                result.quality_score,
            )
        except Exception as exc:
            logger.exception("Resume parse job failed: job_id=%s", job_id)
            job.status = "failed"
            job.stage = "failed"
            job.progress = 100
            job.error_message = str(exc)[:2000]
            job.finished_at = datetime.utcnow()
            source.status = "failed"
            await db.commit()


def run_resume_parse_job(job_id: int) -> None:
    """RQ entrypoint; RQ workers execute synchronous callables."""
    asyncio.run(process_resume_parse_job(job_id))


async def recover_pending_resume_parse_jobs() -> None:
    """Re-enqueue jobs left unfinished after a backend restart."""
    from app.services.task_queue import QueueUnavailable, enqueue_resume_parse_job

    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(ResumeParseJob).where(ResumeParseJob.status.in_(["queued", "processing"]))
        )
        jobs = list(result.scalars().all())
        for job in jobs:
            job.status = "queued"
            job.stage = "queued"
            job.progress = 0
            job.error_message = None
        if jobs:
            await db.commit()

    for job in jobs:
        try:
            queue_job = enqueue_resume_parse_job(job.id)
        except QueueUnavailable as exc:
            logger.warning("Could not recover resume parse job %s: %s", job.id, exc)
            continue
        async with AsyncSessionLocal() as db:
            current_job = await db.get(ResumeParseJob, job.id)
            if current_job:
                current_job.executor = "rq"
                current_job.queue_job_id = queue_job.id
                await db.commit()
