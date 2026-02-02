"""Tests for user-friendly error mapping."""

from src.services.errors import (
    get_user_error,
    WorkflowTimeout,
    QueueFull,
    RateLimited,
    DEFAULT_ERROR,
)


class TestGetUserError:
    def test_known_error_type(self):
        result = get_user_error(WorkflowTimeout("took too long"))
        assert result["error_type"] == "WorkflowTimeout"
        assert "longer than usual" in result["error"]
        assert result["can_retry"] is False  # Suggests specific query, not retry

    def test_queue_full(self):
        result = get_user_error(QueueFull("full"))
        assert result["error_type"] == "QueueFull"
        assert "capacity" in result["error"]
        assert result["can_retry"] is True

    def test_rate_limited(self):
        result = get_user_error(RateLimited("slow down"))
        assert result["error_type"] == "RateLimited"
        assert "too quickly" in result["error"]
        assert result["can_retry"] is False  # Says "wait", not "try again"

    def test_timeout_error(self):
        result = get_user_error(TimeoutError("timed out"))
        assert "taking longer" in result["error"]
        assert result["can_retry"] is True

    def test_connection_error(self):
        result = get_user_error(ConnectionError("refused"))
        assert "connecting" in result["error"]

    def test_unknown_error_returns_default(self):
        result = get_user_error(RuntimeError("something weird"))
        assert result["error"] == DEFAULT_ERROR
        assert result["error_type"] == "RuntimeError"

    def test_response_structure(self):
        result = get_user_error(Exception("test"))
        assert "error" in result
        assert "can_retry" in result
        assert "error_type" in result
