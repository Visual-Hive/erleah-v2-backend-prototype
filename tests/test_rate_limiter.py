"""Tests for rate limiter."""

from src.services.rate_limiter import RateLimiter


class TestRateLimiter:
    def test_allows_within_limit(self):
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is True

    def test_blocks_over_limit(self):
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is False

    def test_separate_keys_independent(self):
        limiter = RateLimiter(max_requests=1, window_seconds=60)
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-2") is True
        # user-1 is now blocked
        assert limiter.is_allowed("user-1") is False
        # user-2 is also blocked
        assert limiter.is_allowed("user-2") is False

    def test_expired_entries_removed(self):
        limiter = RateLimiter(max_requests=1, window_seconds=0.01)
        assert limiter.is_allowed("user-1") is True
        assert limiter.is_allowed("user-1") is False

        import time
        time.sleep(0.02)

        # Should be allowed again after window expires
        assert limiter.is_allowed("user-1") is True

    def test_cleanup_removes_expired_keys(self):
        limiter = RateLimiter(max_requests=1, window_seconds=0.01)
        limiter.is_allowed("user-1")
        limiter.is_allowed("user-2")

        import time
        time.sleep(0.02)

        limiter.cleanup()
        assert "user-1" not in limiter._buckets
        assert "user-2" not in limiter._buckets
