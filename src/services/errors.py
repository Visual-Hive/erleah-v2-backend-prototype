"""User-friendly error message mapping."""

import structlog

logger = structlog.get_logger()

# Map internal error types to user-friendly messages
ERROR_MAP: dict[str, str] = {
    "TimeoutError": "The search is taking longer than expected. Please try again.",
    "asyncio.TimeoutError": "The search is taking longer than expected. Please try again.",
    "ConnectionError": "I'm having trouble connecting to the database. Please try again in a moment.",
    "httpx.ConnectError": "I'm having trouble connecting to the database. Please try again in a moment.",
    "httpx.ConnectTimeout": "I'm having trouble connecting to the database. Please try again in a moment.",
    "CircuitBreakerOpen": "A service is temporarily unavailable. Please try again in a moment.",
    "QdrantError": "The search service is temporarily unavailable. Please try again.",
    "RedisError": "The cache service is temporarily unavailable. This won't affect your results.",
    "WorkflowTimeout": "This is taking longer than usual. Please try a more specific query.",
    "QueueFull": "The system is at capacity. Please try again shortly.",
    "RateLimited": "You're sending requests too quickly. Please wait a moment.",
}

DEFAULT_ERROR = "I encountered an unexpected issue. Please try again."


def get_user_error(error: Exception) -> dict:
    """Convert an internal exception to a user-friendly error response."""
    error_type = type(error).__name__
    # Check direct match
    message = ERROR_MAP.get(error_type)
    # Check module-qualified name
    if not message:
        qualified = f"{type(error).__module__}.{error_type}"
        message = ERROR_MAP.get(qualified)
    # Check if any key is a substring of the error type
    if not message:
        for key, msg in ERROR_MAP.items():
            if key.lower() in error_type.lower() or key.lower() in str(error).lower():
                message = msg
                break
    if not message:
        message = DEFAULT_ERROR

    can_retry = "try again" in message.lower()

    return {
        "error": message,
        "can_retry": can_retry,
        "error_type": error_type,
    }


class WorkflowTimeout(Exception):
    """Raised when the entire agent workflow exceeds the timeout."""
    pass


class QueueFull(Exception):
    """Raised when the request queue is full."""
    pass


class RateLimited(Exception):
    """Raised when a user exceeds the rate limit."""
    pass
