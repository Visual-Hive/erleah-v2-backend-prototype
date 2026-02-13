"""In-memory rate limiter for per-user/conversation throttling."""

import time
from collections import defaultdict

import structlog

logger = structlog.get_logger()


class RateLimiter:
    """Token-bucket rate limiter per key (user_id or conversation_id)."""

    def __init__(self, max_requests: int = 10, window_seconds: float = 60.0):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._buckets: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, key: str) -> bool:
        """Check if a request from this key is allowed."""
        now = time.monotonic()
        bucket = self._buckets[key]

        # Remove expired timestamps
        cutoff = now - self.window_seconds
        self._buckets[key] = [t for t in bucket if t > cutoff]

        if len(self._buckets[key]) >= self.max_requests:
            logger.warning(
                "rate_limit.exceeded", key=key, count=len(self._buckets[key])
            )
            return False

        self._buckets[key].append(now)
        return True

    def cleanup(self) -> None:
        """Remove expired entries to free memory."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        expired_keys = [
            k for k, v in self._buckets.items() if all(t <= cutoff for t in v)
        ]
        for k in expired_keys:
            del self._buckets[k]


# Singleton: 10 requests per 60 seconds per user
_rate_limiter: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        # Increased for stability testing (100 requests per 60 seconds)
        _rate_limiter = RateLimiter(max_requests=100, window_seconds=60.0)
    return _rate_limiter
