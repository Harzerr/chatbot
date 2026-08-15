"""Small, failure-tolerant Redis helpers for derived application data."""

import hashlib
import json
import secrets
from collections.abc import Iterable
from typing import Any

from redis.exceptions import RedisError

from app.services.task_queue import get_redis_connection
from app.utils.logger import setup_logger

logger = setup_logger(__name__)


def stable_cache_key(namespace: str, parts: Iterable[Any]) -> str:
    payload = json.dumps(list(parts), ensure_ascii=False, sort_keys=True, default=str, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"chatbot:{namespace}:{digest}"


class RedisCache:
    """Best-effort cache; Redis failures never fail a user request."""

    def __init__(self, connection=None) -> None:
        self.connection = connection
        self.available: bool | None = None

    def _connection(self):
        if self.connection is None:
            self.connection = get_redis_connection()
        return self.connection

    def get_text(self, key: str) -> str | None:
        try:
            value = self._connection().get(key)
            self.available = True
            if value is None:
                return None
            return value.decode("utf-8") if isinstance(value, bytes) else str(value)
        except (RedisError, OSError) as exc:
            self.available = False
            logger.warning("Redis cache read skipped: key=%s error=%s", key, type(exc).__name__)
            return None

    def set_text(self, key: str, value: str, ttl_seconds: int) -> bool:
        try:
            result = bool(self._connection().setex(key, max(1, int(ttl_seconds)), value))
            self.available = True
            return result
        except (RedisError, OSError) as exc:
            self.available = False
            logger.warning("Redis cache write skipped: key=%s error=%s", key, type(exc).__name__)
            return False

    def delete(self, key: str) -> bool:
        try:
            result = bool(self._connection().delete(key))
            self.available = True
            return result
        except (RedisError, OSError) as exc:
            self.available = False
            logger.warning("Redis cache delete skipped: key=%s error=%s", key, type(exc).__name__)
            return False

    def acquire_lock(self, key: str, ttl_seconds: int) -> str | None:
        token = secrets.token_urlsafe(18)
        try:
            acquired = self._connection().set(key, token, nx=True, ex=max(1, int(ttl_seconds)))
            self.available = True
            return token if acquired else None
        except (RedisError, OSError) as exc:
            self.available = False
            logger.warning("Redis cache lock skipped: key=%s error=%s", key, type(exc).__name__)
            return None

    def release_lock(self, key: str, token: str) -> bool:
        try:
            connection = self._connection()
            release_script = (
                "if redis.call('get', KEYS[1]) == ARGV[1] then "
                "return redis.call('del', KEYS[1]) else return 0 end"
            )
            return bool(connection.eval(release_script, 1, key, token))
        except (RedisError, OSError) as exc:
            logger.warning("Redis cache unlock skipped: key=%s error=%s", key, type(exc).__name__)
            return False
