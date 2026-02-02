"""Tests for the Redis caching service."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.services.cache import CacheService, make_key


class TestMakeKey:
    def test_deterministic_keys(self):
        """Same inputs always produce same key."""
        key1 = make_key("profile", "user-123")
        key2 = make_key("profile", "user-123")
        assert key1 == key2

    def test_different_inputs_different_keys(self):
        key1 = make_key("profile", "user-123")
        key2 = make_key("profile", "user-456")
        assert key1 != key2

    def test_prefix_included(self):
        key = make_key("profile", "user-123")
        assert key.startswith("profile:")

    def test_case_insensitive(self):
        key1 = make_key("emb", "Hello World")
        key2 = make_key("emb", "hello world")
        assert key1 == key2

    def test_whitespace_normalized(self):
        key1 = make_key("emb", " hello ")
        key2 = make_key("emb", "hello")
        assert key1 == key2


class TestCacheService:
    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_connected(self):
        """Graceful degradation: returns None when Redis not connected."""
        cache = CacheService()
        result = await cache.get("any-key")
        assert result is None

    @pytest.mark.asyncio
    async def test_set_skips_empty_results(self):
        """Don't cache empty results."""
        cache = CacheService()
        cache._redis = AsyncMock()

        assert await cache.set("key", []) is False
        assert await cache.set("key", {}) is False
        assert await cache.set("key", None) is False
        cache._redis.set.assert_not_called()

    @pytest.mark.asyncio
    async def test_set_and_get_round_trip(self):
        """Values can be stored and retrieved."""
        cache = CacheService()
        mock_redis = AsyncMock()
        cache._redis = mock_redis

        # Mock set
        mock_redis.set.return_value = True
        result = await cache.set("key", {"data": "value"}, ttl=60)
        assert result is True
        mock_redis.set.assert_called_once()

        # Mock get
        mock_redis.get.return_value = '{"data": "value"}'
        result = await cache.get("key")
        assert result == {"data": "value"}

    @pytest.mark.asyncio
    async def test_graceful_redis_failure_on_get(self):
        """Returns None when Redis raises during get."""
        cache = CacheService()
        mock_redis = AsyncMock()
        mock_redis.get.side_effect = Exception("connection lost")
        cache._redis = mock_redis

        result = await cache.get("key")
        assert result is None

    @pytest.mark.asyncio
    async def test_graceful_redis_failure_on_set(self):
        """Returns False when Redis raises during set."""
        cache = CacheService()
        mock_redis = AsyncMock()
        mock_redis.set.side_effect = Exception("connection lost")
        cache._redis = mock_redis

        result = await cache.set("key", {"data": "value"})
        assert result is False

    @pytest.mark.asyncio
    async def test_delete(self):
        cache = CacheService()
        mock_redis = AsyncMock()
        cache._redis = mock_redis
        mock_redis.delete.return_value = 1

        result = await cache.delete("key")
        assert result is True

    @pytest.mark.asyncio
    async def test_ping_returns_false_when_disconnected(self):
        cache = CacheService()
        assert await cache.ping() is False

    @pytest.mark.asyncio
    async def test_ping_returns_true_when_connected(self):
        cache = CacheService()
        mock_redis = AsyncMock()
        mock_redis.ping.return_value = True
        cache._redis = mock_redis

        assert await cache.ping() is True
