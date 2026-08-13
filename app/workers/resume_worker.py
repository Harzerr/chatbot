from redis import Redis
from rq import Queue, Worker

from app.core.config import settings


def main() -> None:
    connection = Redis.from_url(settings.REDIS_URL)
    connection.ping()
    worker = Worker(
        [
            Queue(name=settings.RESUME_QUEUE_NAME, connection=connection),
            Queue(name=settings.CAREER_FACT_QUEUE_NAME, connection=connection),
            Queue(name=settings.CODE_QUEUE_NAME, connection=connection),
            Queue(name=settings.EVALUATION_QUEUE_NAME, connection=connection),
            Queue(name=settings.CONVERSATION_SUMMARY_QUEUE_NAME, connection=connection),
        ],
        connection=connection,
    )
    worker.work()


if __name__ == "__main__":
    main()
