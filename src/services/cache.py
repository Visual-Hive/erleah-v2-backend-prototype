"""Redis caching service with graceful degradation and metrics."""

import hashlib
import json
import time
from typing import Any

import structlog
from redis.asyncio import Redis

from src.config import settings
from src.monitoring.metrics import CACHE_HIT, CACHE_MISS, CACHE_OPERATION_DURATION

logger = structlog.get_logger()


def make_key(prefix: str, *parts: str) -> str:
    """Build a deterministic cache key: prefix:md5(normalized parts)."""
    normalized = "|".join(str(p).strip().lower() for p in parts)
    digest = hashlib.md5(normalized.encode()).hexdigest()
    return f"{prefix}:{digest}"


class CacheService:
    """Async Redis cache with JSON serialization and graceful degradation."""

    def __init__(self) -> None:
        self._redis: Redis | None = None

    async def connect(self) -> None:
        try:
            self._redis = Redis.from_url(
                settings.redis_url,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_keepalive=True,
                max_connections=50,
                retry_on_timeout=True,
            )
            await self._redis.ping()
            logger.info("cache.connected", url=settings.redis_url)
        except Exception as e:
            logger.warning("cache.connect_failed", error=str(e))
            self._redis = None

    async def close(self) -> None:
        if self._redis:
            await self._redis.close()
            logger.info("cache.closed")

    async def get(self, key: str, cache_type: str = "general") -> Any | None:
        """Get a value from cache. Returns None on miss or Redis failure."""
        if not self._redis:
            return None
        start = time.perf_counter()
        try:
            raw = await self._redis.get(key)
            duration = time.perf_counter() - start
            CACHE_OPERATION_DURATION.labels(operation="get").observe(duration)
            if raw is None:
                CACHE_MISS.labels(cache_type=cache_type).inc()
                return None
            CACHE_HIT.labels(cache_type=cache_type).inc()
            return json.loads(raw)
        except Exception as e:
            logger.warning("cache.get_failed", key=key, error=str(e))
            return None

    async def set(self, key: str, value: Any, ttl: int = 300) -> bool:
        """Set a value in cache. Skips empty results ([], {}, None). Returns success."""
        if not self._redis:
            return False
        # Don't cache empty results
        if value is None or value == [] or value == {}:
            return False
        start = time.perf_counter()
        try:
            raw = json.dumps(value, default=str)
            await self._redis.set(key, raw, ex=ttl)
            duration = time.perf_counter() - start
            CACHE_OPERATION_DURATION.labels(operation="set").observe(duration)
            return True
        except Exception as e:
            logger.warning("cache.set_failed", key=key, error=str(e))
            return False

    async def delete(self, key: str) -> bool:
        """Delete a key from cache."""
        if not self._redis:
            return False
        try:
            await self._redis.delete(key)
            return True
        except Exception as e:
            logger.warning("cache.delete_failed", key=key, error=str(e))
            return False

    async def delete_pattern(self, pattern: str) -> int:
        """Delete all keys matching a pattern (e.g. 'profile:*'). Returns count deleted."""
        if not self._redis:
            return 0
        try:
            deleted = 0
            async for key in self._redis.scan_iter(match=pattern, count=100):
                await self._redis.delete(key)
                deleted += 1
            return deleted
        except Exception as e:
            logger.warning("cache.delete_pattern_failed", pattern=pattern, error=str(e))
            return 0

    @property
    def is_connected(self) -> bool:
        return self._redis is not None

    async def ping(self) -> bool:
        """Check Redis connectivity."""
        if not self._redis:
            return False
        try:
            await self._redis.ping()
            return True
        except Exception:
            return False

    async def publish(self, channel: str, message: str) -> bool:
        """Publish a message to a Redis pub/sub channel."""
        if not self._redis:
            return False
        try:
            await self._redis.publish(channel, message)
            return True
        except Exception as e:
            logger.warning("cache.publish_failed", channel=channel, error=str(e))
            return False


# Singleton
_cache_service: CacheService | None = None


def get_cache_service() -> CacheService:
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service
