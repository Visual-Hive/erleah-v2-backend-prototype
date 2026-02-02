"""Tests for circuit breaker and retry patterns."""

import asyncio
import time

import pytest

from src.services.resilience import (
    CircuitBreaker,
    CircuitBreakerOpen,
    CircuitState,
    async_retry,
    get_circuit_breaker,
)


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker(name="test")
        assert cb.state == CircuitState.CLOSED

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(name="test", failure_threshold=5)
        for _ in range(4):
            cb.record_failure()
        assert cb.state == CircuitState.CLOSED

    def test_opens_at_threshold(self):
        cb = CircuitBreaker(name="test", failure_threshold=3)
        for _ in range(3):
            cb.record_failure()
        assert cb.state == CircuitState.OPEN

    def test_transitions_to_half_open_after_recovery(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN

    def test_closes_on_success_from_half_open(self):
        cb = CircuitBreaker(name="test", failure_threshold=1, recovery_timeout=0.01)
        cb.record_failure()
        time.sleep(0.02)
        assert cb.state == CircuitState.HALF_OPEN
        cb.record_success()
        assert cb.state == CircuitState.CLOSED

    def test_resets_failure_count_on_success(self):
        cb = CircuitBreaker(name="test", failure_threshold=3)
        cb.record_failure()
        cb.record_failure()
        cb.record_success()
        cb.record_failure()
        cb.record_failure()
        # Should still be closed (count reset after success)
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_call_succeeds_when_closed(self):
        cb = CircuitBreaker(name="test")

        async def success():
            return "ok"

        result = await cb.call(success)
        assert result == "ok"

    @pytest.mark.asyncio
    async def test_call_raises_when_open(self):
        cb = CircuitBreaker(name="test", failure_threshold=1)
        cb.record_failure()

        async def success():
            return "ok"

        with pytest.raises(CircuitBreakerOpen):
            await cb.call(success)

    @pytest.mark.asyncio
    async def test_call_records_failure_on_exception(self):
        cb = CircuitBreaker(name="test", failure_threshold=3)

        async def failing():
            raise ValueError("boom")

        with pytest.raises(ValueError):
            await cb.call(failing)

        assert cb._failure_count == 1


class TestGetCircuitBreaker:
    def test_returns_same_instance(self):
        from src.services.resilience import _breakers
        _breakers.clear()
        cb1 = get_circuit_breaker("svc-a")
        cb2 = get_circuit_breaker("svc-a")
        assert cb1 is cb2

    def test_different_names_different_instances(self):
        from src.services.resilience import _breakers
        _breakers.clear()
        cb1 = get_circuit_breaker("svc-a")
        cb2 = get_circuit_breaker("svc-b")
        assert cb1 is not cb2


class TestAsyncRetry:
    @pytest.mark.asyncio
    async def test_succeeds_without_retry(self):
        call_count = 0

        @async_retry(max_retries=3, base_delay=0.01)
        async def success():
            nonlocal call_count
            call_count += 1
            return "ok"

        result = await success()
        assert result == "ok"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure_then_succeeds(self):
        call_count = 0

        @async_retry(max_retries=3, base_delay=0.01)
        async def flaky():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("temporary")
            return "recovered"

        result = await flaky()
        assert result == "recovered"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        @async_retry(max_retries=2, base_delay=0.01)
        async def always_fails():
            raise ValueError("permanent")

        with pytest.raises(ValueError, match="permanent"):
            await always_fails()

    @pytest.mark.asyncio
    async def test_only_retries_specified_exceptions(self):
        call_count = 0

        @async_retry(max_retries=3, base_delay=0.01, exceptions=(ConnectionError,))
        async def wrong_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("not retryable")

        with pytest.raises(ValueError):
            await wrong_error()
        assert call_count == 1  # No retries for ValueError
