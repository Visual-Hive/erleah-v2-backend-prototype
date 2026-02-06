"""Resilience patterns: circuit breaker and retry decorators."""

import asyncio
import time
from enum import Enum
from functools import wraps
from typing import Any, Callable

import structlog

logger = structlog.get_logger()


# --- Circuit Breaker ---


class CircuitState(Enum):
    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject immediately
    HALF_OPEN = "half_open"  # Testing if service recovered


class CircuitBreaker:
    """Async circuit breaker for external service calls."""

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout: float = 60.0,
        half_open_max_calls: int = 1,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls

        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._last_failure_time: float = 0
        self._half_open_calls = 0

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN:
            # Check if recovery timeout has elapsed
            if time.monotonic() - self._last_failure_time >= self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                self._half_open_calls = 0
                logger.info("circuit_breaker.half_open", name=self.name)
        return self._state

    def record_success(self) -> None:
        if self._state == CircuitState.HALF_OPEN:
            self._state = CircuitState.CLOSED
            logger.info("circuit_breaker.closed", name=self.name)
        self._failure_count = 0

    def record_failure(self) -> None:
        self._failure_count += 1
        self._last_failure_time = time.monotonic()
        if self._failure_count >= self.failure_threshold:
            self._state = CircuitState.OPEN
            logger.warning(
                "circuit_breaker.open",
                name=self.name,
                failures=self._failure_count,
            )

    async def call(self, func: Callable, *args: Any, **kwargs: Any) -> Any:
        """Execute function through the circuit breaker."""
        state = self.state
        if state == CircuitState.OPEN:
            raise CircuitBreakerOpen(f"Circuit breaker '{self.name}' is open")

        if state == CircuitState.HALF_OPEN:
            self._half_open_calls += 1
            if self._half_open_calls > self.half_open_max_calls:
                raise CircuitBreakerOpen(
                    f"Circuit breaker '{self.name}' half-open limit reached"
                )

        try:
            result = await func(*args, **kwargs)
            self.record_success()
            return result
        except CircuitBreakerOpen:
            raise
        except Exception:
            self.record_failure()
            raise


class CircuitBreakerOpen(Exception):
    """Raised when circuit breaker is in open state."""

    pass


# Named circuit breakers for external services
_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(name: str) -> CircuitBreaker:
    if name not in _breakers:
        _breakers[name] = CircuitBreaker(name=name)
    return _breakers[name]


# --- Retry with backoff ---


def async_retry(
    max_retries: int = 3,
    base_delay: float = 0.5,
    max_delay: float = 10.0,
    exceptions: tuple = (Exception,),
):
    """Decorator for async retry with exponential backoff.

    Replaces tenacity to avoid an extra dependency while providing
    the same core functionality.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_exception: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    last_exception = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2**attempt), max_delay)
                        logger.warning(
                            "retry.attempt",
                            func=func.__name__,
                            attempt=attempt + 1,
                            max_retries=max_retries,
                            delay=delay,
                            error=str(e),
                        )
                        await asyncio.sleep(delay)
            # last_exception is guaranteed non-None since max_retries + 1 >= 1
            assert last_exception is not None
            raise last_exception

        return wrapper

    return decorator
