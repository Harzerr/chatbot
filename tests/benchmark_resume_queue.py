import asyncio
import json
import multiprocessing
import os
import resource
import sys
import tempfile
import time
from pathlib import Path

from redis import Redis
from rq import Queue, SimpleWorker
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.base import Base
from app.models.resume import ResumeParseJob, ResumeSource
from app.models.user import User
from app.services import resume_jobs, task_queue


def read_rss_mb(pid: int = 0) -> float:
    target = pid or os.getpid()
    status_path = Path(f"/proc/{target}/status")
    for line in status_path.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            return round(int(line.split()[1]) / 1024, 2)
    return 0.0


async def create_schema(engine):
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)


async def create_job(session_factory, pdf_path: Path, temp_dir: Path, index: int) -> int:
    stored_path = temp_dir / f"resume-{index}.pdf"
    stored_path.write_bytes(pdf_path.read_bytes())
    async with session_factory() as db:
        user = User(
            username=f"resume-benchmark-{index}",
            password="benchmark-only",
            tenant_id="resume-benchmark",
            full_name="基准测试用户",
            email=f"resume-benchmark-{index}@example.com",
            phone="13800000000",
            target_role="Python 后端工程师",
            years_of_experience=1,
        )
        db.add(user)
        await db.flush()
        source = ResumeSource(
            user_id=user.id,
            original_filename=stored_path.name,
            stored_path=str(stored_path),
            content_type="application/pdf",
            file_size=stored_path.stat().st_size,
            sha256="benchmark",
            status="uploaded",
        )
        db.add(source)
        await db.flush()
        job = ResumeParseJob(
            user_id=user.id,
            source_id=source.id,
            status="queued",
            stage="queued",
            progress=0,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def get_job(session_factory, job_id: int) -> ResumeParseJob:
    async with session_factory() as db:
        return await db.get(ResumeParseJob, job_id)


def worker_process(redis_url: str, queue_name: str, database_url: str, result_queue):
    child_engine = create_async_engine(database_url)
    resume_jobs.AsyncSessionLocal = async_sessionmaker(
        bind=child_engine,
        expire_on_commit=False,
    )
    settings.REDIS_URL = redis_url
    settings.RESUME_QUEUE_NAME = queue_name
    connection = Redis.from_url(redis_url)
    queue = Queue(
        name=queue_name,
        connection=connection,
        default_timeout=settings.RESUME_QUEUE_TIMEOUT,
    )
    started = time.perf_counter()
    try:
        worker = SimpleWorker([queue], connection=connection)
        worker.work(burst=True, with_scheduler=False)
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        peak_rss_mb = round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2)
        result_queue.put({"duration_ms": duration_ms, "peak_rss_mb": peak_rss_mb})
    except Exception as exc:
        result_queue.put({"error": repr(exc)})
        raise
    finally:
        asyncio.run(child_engine.dispose())


def wait_for_completion(session_factory, job_id: int, timeout_seconds: float = 60):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        job = asyncio.run(get_job(session_factory, job_id))
        if job.status in {"completed", "failed"}:
            return job
        time.sleep(0.05)
    raise TimeoutError(f"Job {job_id} did not finish within {timeout_seconds}s")


def main():
    pdf_path = Path(
        os.getenv(
            "RESUME_BENCHMARK_PDF",
            "uploads/resumes/user_2_a32e665fa0ff44b693ddf3e5cc338678.pdf",
        )
    ).resolve()
    if not pdf_path.is_file():
        raise SystemExit(f"Benchmark PDF does not exist: {pdf_path}")

    redis_url = os.getenv("RESUME_TEST_REDIS_URL", "redis://127.0.0.1:6379/15")
    redis = Redis.from_url(redis_url)
    redis.ping()
    queue_name = f"resume_parse_benchmark_{os.getpid()}"
    original_redis_url = settings.REDIS_URL
    original_queue_name = settings.RESUME_QUEUE_NAME
    settings.REDIS_URL = redis_url
    settings.RESUME_QUEUE_NAME = queue_name

    temp_dir = Path(tempfile.mkdtemp(prefix="resume-benchmark-"))
    engine = create_async_engine(f"sqlite+aiosqlite:///{temp_dir / 'benchmark.db'}")
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    original_session_factory = resume_jobs.AsyncSessionLocal
    resume_jobs.AsyncSessionLocal = session_factory

    try:
        asyncio.run(create_schema(engine))

        sync_job_id = asyncio.run(create_job(session_factory, pdf_path, temp_dir, 1))
        sync_before_rss = read_rss_mb()
        sync_started = time.perf_counter()
        asyncio.run(resume_jobs.process_resume_parse_job(sync_job_id))
        sync_duration_ms = round((time.perf_counter() - sync_started) * 1000, 2)
        sync_after_rss = read_rss_mb()
        sync_job = asyncio.run(get_job(session_factory, sync_job_id))
        if sync_job.status != "completed":
            raise RuntimeError(f"Synchronous baseline failed: {sync_job.error_message}")

        async_job_id = asyncio.run(create_job(session_factory, pdf_path, temp_dir, 2))
        async_before_rss = read_rss_mb()
        enqueue_started = time.perf_counter()
        queue_job = task_queue.enqueue_resume_parse_job(async_job_id)
        enqueue_duration_ms = round((time.perf_counter() - enqueue_started) * 1000, 2)

        async_worker_result = multiprocessing.Queue()
        worker_process_instance = multiprocessing.Process(
            target=worker_process,
            args=(
                redis_url,
                queue_name,
                f"sqlite+aiosqlite:///{temp_dir / 'benchmark.db'}",
                async_worker_result,
            ),
        )
        worker_started = time.perf_counter()
        worker_process_instance.start()
        async_job = wait_for_completion(session_factory, async_job_id)
        worker_process_instance.join(timeout=60)
        if worker_process_instance.is_alive():
            worker_process_instance.terminate()
            raise TimeoutError("RQ benchmark worker did not exit")
        worker_duration_ms = round((time.perf_counter() - worker_started) * 1000, 2)
        worker_result = async_worker_result.get(timeout=5)
        async_after_rss = read_rss_mb()
        if async_job.status != "completed":
            raise RuntimeError(f"Asynchronous benchmark failed: {async_job.error_message}")

        result = {
            "pdf": str(pdf_path),
            "pdf_size_mb": round(pdf_path.stat().st_size / 1024 / 1024, 3),
            "sync_baseline": {
                "parse_duration_ms": sync_duration_ms,
                "backend_rss_before_mb": sync_before_rss,
                "backend_rss_after_mb": sync_after_rss,
                "backend_rss_delta_mb": round(sync_after_rss - sync_before_rss, 2),
                "status": sync_job.status,
            },
            "redis_rq": {
                "enqueue_duration_ms": enqueue_duration_ms,
                "worker_end_to_end_ms": worker_duration_ms,
                "worker_parse_ms": worker_result["duration_ms"],
                "backend_rss_before_mb": async_before_rss,
                "backend_rss_after_mb": async_after_rss,
                "backend_rss_delta_mb": round(async_after_rss - async_before_rss, 2),
                "worker_peak_rss_mb": worker_result["peak_rss_mb"],
                "queue_job_id": queue_job.id,
                "status": async_job.status,
            },
        }
        result["request_latency_reduction_percent"] = round(
            (1 - result["redis_rq"]["enqueue_duration_ms"] / result["sync_baseline"]["parse_duration_ms"])
            * 100,
            2,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
    finally:
        redis.delete(f"rq:queue:{queue_name}")
        resume_jobs.AsyncSessionLocal = original_session_factory
        settings.REDIS_URL = original_redis_url
        settings.RESUME_QUEUE_NAME = original_queue_name
        asyncio.run(engine.dispose())
        for path in sorted(temp_dir.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink()
            elif path.is_dir():
                path.rmdir()
        temp_dir.rmdir()


if __name__ == "__main__":
    multiprocessing.set_start_method("spawn", force=True)
    main()
