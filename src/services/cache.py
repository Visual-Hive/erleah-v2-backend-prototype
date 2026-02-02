"""Redis caching service with graceful degradation."""

import hashlib
import json
from typing import Any

import structlog
from redis.asyncio import Redis

from src.config import settings

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

    async def get(self, key: str) -> Any | None:
        """Get a value from cache. Returns None on miss or Redis failure."""
        if not self._redis:
            return None
        try:
            raw = await self._redis.get(key)
            if raw is None:
                return None
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
        try:
            raw = json.dumps(value, default=str)
            await self._redis.set(key, raw, ex=ttl)
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


# Singleton
_cache_service: CacheService | None = None


def get_cache_service() -> CacheService:
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service
