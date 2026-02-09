"""Tests for the graceful failure system (Phase 2, TASK-01).

Covers:
- Error classification (classify_error)
- Error context building (build_error_context)
- @graceful_node decorator behavior (non-critical + critical)
- Last-resort fallback messages in generate_response
- Error section building for prompts
"""

import asyncio

import pytest

from src.agent.nodes.error_wrapper import (
    build_error_context,
    classify_error,
    graceful_node,
)
from src.agent.nodes.generate_response import (
    LAST_RESORT_MESSAGES,
    _build_error_section,
)
from src.services.resilience import CircuitBreakerOpen


# ---------------------------------------------------------------------------
# classify_error
# ---------------------------------------------------------------------------


class TestClassifyError:
    """Error classification maps exceptions to user-friendly categories."""

    def test_timeout_from_exception_type(self):
        assert classify_error(TimeoutError("request timed out")) == "timeout"

    def test_timeout_from_asyncio(self):
        assert classify_error(asyncio.TimeoutError("deadline exceeded")) == "timeout"

    def test_timeout_from_message(self):
        assert classify_error(Exception("Connection timeout after 10s")) == "timeout"

    def test_connection_error(self):
        assert classify_error(ConnectionError("refused")) == "connection"

    def test_connection_from_message(self):
        assert classify_error(Exception("Failed to connect to host")) == "connection"

    def test_circuit_breaker_open(self):
        assert classify_error(CircuitBreakerOpen("directus circuit open")) == "connection"

    def test_rate_limit_from_message(self):
        assert classify_error(Exception("429 rate limit exceeded")) == "rate_limit"

    def test_rate_limit_from_quota(self):
        assert classify_error(Exception("API quota exhausted")) == "rate_limit"

    def test_not_found(self):
        assert classify_error(Exception("Resource not found (404)")) == "not_found"

    def test_data_validation_error(self):
        assert classify_error(Exception("validation failed")) == "data"

    def test_json_decode_error(self):
        assert classify_error(ValueError("invalid JSON")) == "data"

    def test_unknown_error(self):
        assert classify_error(Exception("something completely unexpected")) == "unknown"

    def test_unknown_runtime_error(self):
        assert classify_error(RuntimeError("mysterious failure")) == "unknown"


# ---------------------------------------------------------------------------
# build_error_context
# ---------------------------------------------------------------------------


class TestBuildErrorContext:
    """Error context builder produces structured context for the response generator."""

    def _base_state(self, **overrides):
        state = {
            "trace_id": "test-trace",
            "user_profile": {},
            "conversation_history": [],
            "acknowledgment_text": "",
            "planned_queries": [],
            "query_results": {},
        }
        state.update(overrides)
        return state

    def test_basic_context_fields(self):
        ctx = build_error_context(
            "fetch_data",
            ConnectionError("Directus is down"),
            self._base_state(),
        )
        assert ctx["failed_node"] == "fetch_data"
        assert ctx["error_type"] == "connection"
        assert ctx["degraded_results"] is True
        assert ctx["can_retry"] is True
        assert "Directus is down" in ctx["error_detail"]

    def test_node_specific_hint(self):
        ctx = build_error_context(
            "execute_queries",
            TimeoutError("search timed out"),
            self._base_state(),
        )
        assert "too long" in ctx["user_hint"].lower()

    def test_default_hint_for_unknown_node(self):
        ctx = build_error_context(
            "mystery_node",
            Exception("wat"),
            self._base_state(),
        )
        assert "unexpected" in ctx["user_hint"].lower()

    def test_available_data_tracking_with_profile(self):
        ctx = build_error_context(
            "execute_queries",
            TimeoutError(),
            self._base_state(user_profile={"name": "Alice"}),
        )
        assert "profile" in ctx["available_data"]

    def test_available_data_tracking_with_results(self):
        ctx = build_error_context(
            "generate_response",
            TimeoutError(),
            self._base_state(
                query_results={"sessions": [{"id": "1"}], "exhibitors": []},
            ),
        )
        assert "search:sessions" in ctx["available_data"]
        assert "search:exhibitors" in ctx["unavailable_data"]

    def test_unavailable_search_for_search_node(self):
        ctx = build_error_context(
            "execute_queries",
            ConnectionError("qdrant down"),
            self._base_state(),
        )
        assert "search_results" in ctx["unavailable_data"]

    def test_retry_suggestion_for_timeout(self):
        ctx = build_error_context(
            "plan_queries",
            TimeoutError(),
            self._base_state(),
        )
        assert ctx["can_retry"] is True
        assert "try" in ctx["retry_suggestion"].lower()

    def test_no_retry_for_data_error(self):
        ctx = build_error_context(
            "plan_queries",
            Exception("validation failed"),
            self._base_state(),
        )
        assert ctx["can_retry"] is False


# ---------------------------------------------------------------------------
# @graceful_node decorator
# ---------------------------------------------------------------------------


class TestGracefulNodeDecorator:
    """The decorator catches exceptions and returns degraded state updates."""

    @pytest.mark.asyncio
    async def test_successful_node_passes_through(self):
        """Decorator is transparent for successful nodes."""

        @graceful_node("test_node")
        async def happy_node(state):
            return {"result": "all good", "current_node": "test_node"}

        result = await happy_node({"trace_id": "t1"})
        assert result["result"] == "all good"
        assert "error_context" not in result

    @pytest.mark.asyncio
    async def test_non_critical_failure_continues_pipeline(self):
        """Non-critical node failure sets partial_failure but NOT force_response."""

        @graceful_node("fetch_data", critical=False)
        async def failing_node(state):
            raise ConnectionError("Directus is down")

        result = await failing_node({"trace_id": "t1"})
        assert result["partial_failure"] is True
        assert result["error_context"]["error_type"] == "connection"
        assert result["error_context"]["failed_node"] == "fetch_data"
        assert result["error_node"] == "fetch_data"
        # Non-critical: force_response should NOT be set
        assert "force_response" not in result or result.get("force_response") is not True

    @pytest.mark.asyncio
    async def test_critical_failure_forces_response(self):
        """Critical node failure sets force_response=True to skip to generate_response."""

        @graceful_node("plan_queries", critical=True)
        async def critical_node(state):
            raise TimeoutError("LLM timed out")

        result = await critical_node({"trace_id": "t1"})
        assert result["partial_failure"] is True
        assert result["force_response"] is True
        assert result["error_context"]["error_type"] == "timeout"

    @pytest.mark.asyncio
    async def test_error_message_includes_node_name(self):
        """The error field includes the node name for debugging."""

        @graceful_node("execute_queries")
        async def failing_node(state):
            raise RuntimeError("Qdrant exploded")

        result = await failing_node({"trace_id": "t1"})
        assert "execute_queries" in result["error"]
        assert "Qdrant exploded" in result["error"]

    @pytest.mark.asyncio
    async def test_preserves_function_name(self):
        """functools.wraps preserves the original function's name."""

        @graceful_node("test_node")
        async def my_cool_function(state):
            return {}

        assert my_cool_function.__name__ == "my_cool_function"

    @pytest.mark.asyncio
    async def test_state_data_flows_to_error_context(self):
        """Error context includes available data from state."""

        @graceful_node("generate_response")
        async def failing_node(state):
            raise Exception("something broke")

        state = {
            "trace_id": "t1",
            "user_profile": {"name": "Alice"},
            "conversation_history": [{"role": "user", "text": "hi"}],
            "acknowledgment_text": "Got it!",
            "planned_queries": [{"table": "sessions"}],
            "query_results": {"sessions": [{"id": "s1"}]},
        }
        result = await failing_node(state)
        ctx = result["error_context"]
        assert "profile" in ctx["available_data"]
        assert "conversation_history" in ctx["available_data"]
        assert "acknowledgment" in ctx["available_data"]
        assert "search_plan" in ctx["available_data"]
        assert "search:sessions" in ctx["available_data"]


# ---------------------------------------------------------------------------
# _build_error_section (for prompt injection)
# ---------------------------------------------------------------------------


class TestBuildErrorSection:
    """Error section builder for the generate_response system prompt."""

    def test_no_error_returns_empty(self):
        state = {"error_context": None}
        assert _build_error_section(state) == ""

    def test_error_context_produces_section(self):
        state = {
            "error_context": {
                "failed_node": "execute_queries",
                "error_type": "timeout",
                "user_hint": "Search is slow right now.",
                "available_data": ["profile"],
                "unavailable_data": ["search_results"],
                "retry_suggestion": "Try again in a moment.",
            }
        }
        section = _build_error_section(state)
        assert "Error Context" in section
        assert "execute_queries" in section
        assert "timeout" in section
        assert "Search is slow" in section
        assert "profile" in section
        assert "search_results" in section
        assert "Try again" in section

    def test_missing_optional_fields(self):
        """Section still builds even if some optional fields are missing."""
        state = {
            "error_context": {
                "failed_node": "plan_queries",
                "error_type": "unknown",
            }
        }
        section = _build_error_section(state)
        assert "plan_queries" in section
        assert "unknown" in section


# ---------------------------------------------------------------------------
# Last-resort fallback messages
# ---------------------------------------------------------------------------


class TestLastResortMessages:
    """Verify fallback messages exist for all classified error types."""

    def test_timeout_fallback_exists(self):
        assert "timeout" in LAST_RESORT_MESSAGES
        assert len(LAST_RESORT_MESSAGES["timeout"]) > 20

    def test_connection_fallback_exists(self):
        assert "connection" in LAST_RESORT_MESSAGES
        assert len(LAST_RESORT_MESSAGES["connection"]) > 20

    def test_rate_limit_fallback_exists(self):
        assert "rate_limit" in LAST_RESORT_MESSAGES
        assert len(LAST_RESORT_MESSAGES["rate_limit"]) > 20

    def test_default_fallback_exists(self):
        assert "default" in LAST_RESORT_MESSAGES
        assert len(LAST_RESORT_MESSAGES["default"]) > 20

    def test_no_fallback_shows_raw_errors(self):
        """None of the fallback messages contain technical details."""
        for key, msg in LAST_RESORT_MESSAGES.items():
            assert "traceback" not in msg.lower()
            assert "exception" not in msg.lower()
            assert "stack" not in msg.lower()
