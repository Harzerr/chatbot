from uuid import uuid4

from redis import Redis
from redis.exceptions import RedisError
from rq import Queue
from rq.job import Job

from app.core.config import settings


class QueueUnavailable(RuntimeError):
    pass


def get_redis_connection() -> Redis:
    return Redis.from_url(settings.REDIS_URL, socket_connect_timeout=3, socket_timeout=5)


def get_resume_queue() -> Queue:
    try:
        connection = get_redis_connection()
        connection.ping()
        return Queue(
            name=settings.RESUME_QUEUE_NAME,
            connection=connection,
            default_timeout=settings.RESUME_QUEUE_TIMEOUT,
        )
    except RedisError as exc:
        raise QueueUnavailable("Resume parse queue is unavailable") from exc


def get_career_fact_queue() -> Queue:
    try:
        connection = get_redis_connection()
        connection.ping()
        return Queue(
            name=settings.CAREER_FACT_QUEUE_NAME,
            connection=connection,
            default_timeout=settings.CAREER_FACT_QUEUE_TIMEOUT,
        )
    except RedisError as exc:
        raise QueueUnavailable("Career fact extraction queue is unavailable") from exc


def get_code_queue() -> Queue:
    try:
        connection = get_redis_connection()
        connection.ping()
        return Queue(
            name=settings.CODE_QUEUE_NAME,
            connection=connection,
            default_timeout=settings.CODE_QUEUE_TIMEOUT,
        )
    except RedisError as exc:
        raise QueueUnavailable("Code execution queue is unavailable") from exc


def get_evaluation_queue() -> Queue:
    try:
        connection = get_redis_connection()
        connection.ping()
        return Queue(
            name=settings.EVALUATION_QUEUE_NAME,
            connection=connection,
            default_timeout=settings.EVALUATION_QUEUE_TIMEOUT,
        )
    except RedisError as exc:
        raise QueueUnavailable("Interview evaluation queue is unavailable") from exc


def get_conversation_summary_queue() -> Queue:
    try:
        connection = get_redis_connection()
        connection.ping()
        return Queue(
            name=settings.CONVERSATION_SUMMARY_QUEUE_NAME,
            connection=connection,
            default_timeout=settings.CONVERSATION_SUMMARY_QUEUE_TIMEOUT,
        )
    except RedisError as exc:
        raise QueueUnavailable("Conversation summary queue is unavailable") from exc


def enqueue_resume_parse_job(job_id: int):
    try:
        queue = get_resume_queue()
        return queue.enqueue(
            "app.services.resume_jobs.run_resume_parse_job",
            job_id,
            job_id=f"resume-parse-{job_id}-{uuid4().hex}",
            result_ttl=86400,
            failure_ttl=604800,
        )
    except (RedisError, OSError) as exc:
        raise QueueUnavailable("Resume parse queue is unavailable") from exc


def enqueue_career_fact_job(payload: dict, user_id: int):
    try:
        queue = get_career_fact_queue()
        job = queue.enqueue(
            "app.services.career_fact_jobs.run_career_fact_job",
            payload,
            job_id=f"career-fact-{uuid4().hex}",
            result_ttl=86400,
            failure_ttl=604800,
        )
        job.meta["user_id"] = str(user_id)
        job.save_meta()
        return job
    except (RedisError, OSError) as exc:
        raise QueueUnavailable("Career fact extraction queue is unavailable") from exc


def enqueue_code_run_job(payload: dict, user_id: int):
    try:
        queue = get_code_queue()
        job = queue.enqueue(
            "app.services.code_jobs.run_code_job",
            payload,
            job_id=f"code-run-{uuid4().hex}",
            result_ttl=3600,
            failure_ttl=3600,
        )
        job.meta["user_id"] = str(user_id)
        job.save_meta()
        return job
    except (RedisError, OSError) as exc:
        raise QueueUnavailable("Code execution queue is unavailable") from exc


def enqueue_evaluation_job(payload: dict):
    try:
        queue = get_evaluation_queue()
        return queue.enqueue(
            "app.services.evaluation_jobs.run_evaluation_job",
            payload,
            job_id=f"interview-evaluation-{uuid4().hex}",
            result_ttl=86400,
            failure_ttl=604800,
        )
    except (RedisError, OSError) as exc:
        raise QueueUnavailable("Interview evaluation queue is unavailable") from exc


def enqueue_conversation_summary_job(payload: dict):
    try:
        queue = get_conversation_summary_queue()
        return queue.enqueue(
            "app.services.conversation_summary_jobs.run_conversation_summary_job",
            payload,
            job_id=f"conversation-summary-{uuid4().hex}",
            result_ttl=86400,
            failure_ttl=604800,
        )
    except (RedisError, OSError) as exc:
        raise QueueUnavailable("Conversation summary queue is unavailable") from exc


def get_code_job(job_id: str) -> Job:
    try:
        return Job.fetch(job_id, connection=get_redis_connection())
    except RedisError as exc:
        raise QueueUnavailable("Code execution queue is unavailable") from exc


def get_career_fact_job(job_id: str) -> Job:
    try:
        return Job.fetch(job_id, connection=get_redis_connection())
    except RedisError as exc:
        raise QueueUnavailable("Career fact extraction queue is unavailable") from exc
