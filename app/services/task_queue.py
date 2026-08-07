from uuid import uuid4

from redis import Redis
from redis.exceptions import RedisError
from rq import Queue

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
