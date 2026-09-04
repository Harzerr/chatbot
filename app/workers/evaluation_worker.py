from redis import Redis
from rq import Queue, Worker

from app.core.config import settings


def main() -> None:
    connection = Redis.from_url(settings.REDIS_URL)
    connection.ping()
    Worker(
        [Queue(name=settings.EVALUATION_QUEUE_NAME, connection=connection)],
        connection=connection,
    ).work(with_scheduler=True)


if __name__ == "__main__":
    main()
