"""Graceful failure decorator for LangGraph nodes.

Wraps any async pipeline node so it never crashes the pipeline.
On failure, it populates ErrorContext in the state and either:
  - Continues with degraded results (non-critical nodes)
  - Sets force_response=True to skip to generate_response (critical nodes)

The generate_response node reads the ErrorContext and crafts a natural,
helpful message explaining what happened.

Part of Phase 2 TASK-01: Graceful Failure System.
"""

import functools
import traceback
from typing import Any, Callable

import structlog

from src.agent.state import ErrorContext

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Error classification
# ---------------------------------------------------------------------------


def classify_error(error: Exception) -> str:
    """Classify an exception into a user-friendly category.

    Returns one of: "timeout", "connection", "rate_limit", "not_found", "data", "unknown".
    """
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()

    if "timeout" in error_str or "timeout" in error_type:
        return "timeout"
    if (
        "connection" in error_str
        or "connect" in error_str
        or "connection" in error_type
        or "circuit" in error_type
    ):
        return "connection"
    if "rate" in error_str or "429" in error_str or "quota" in error_str:
        return "rate_limit"
    if "not found" in error_str or "404" in error_str:
        return "not_found"
    if "validation" in error_str or "invalid" in error_str or "json" in error_type:
        return "data"
    return "unknown"


# ---------------------------------------------------------------------------
# Node-specific user hints
# ---------------------------------------------------------------------------

_NODE_HINTS: dict[str, dict[str, str]] = {
    "fetch_data": {
        "timeout": "I wasn't able to load all the data I needed. I'll do my best with what I have.",
        "connection": "I'm having trouble reaching the database right now.",
        "rate_limit": "I'm getting a lot of requests right now. Let me try with what I have.",
    },
    "plan_queries": {
        "timeout": "My search planning is taking too long. I'll try a simpler approach.",
        "rate_limit": "I'm getting a lot of requests right now. Let me try a simpler search.",
        "data": "I had trouble understanding the request. Could you try rephrasing?",
    },
    "execute_queries": {
        "timeout": "The search is taking too long. I may have partial results.",
        "connection": "The search database isn't responding. I'll try to help with what I know.",
        "rate_limit": "The search service is busy. I'll work with limited results.",
    },
    "check_results": {
        "timeout": "Result checking timed out, but I'll work with what I have.",
    },
    "relax_and_retry": {
        "timeout": "The expanded search timed out. I'll use the original results.",
        "connection": "Couldn't expand the search, but I'll do my best with initial results.",
    },
    "generate_acknowledgment": {
        "timeout": "I couldn't generate a quick acknowledgment, but I'm still working on your answer.",
        "connection": "The acknowledgment service is unavailable, but your answer is on the way.",
    },
    "update_profile": {
        "timeout": "Profile update timed out, but I can still help with your question.",
        "connection": "Couldn't update your profile right now, but that doesn't affect your answer.",
    },
    "generate_response": {
        "rate_limit": "I'm temporarily overloaded. Please try again in a moment.",
        "timeout": "I'm having trouble forming a response. Please try a shorter question.",
    },
    "evaluate": {
        "timeout": "Quality evaluation timed out — doesn't affect your answer.",
        "connection": "Couldn't run quality check — doesn't affect your answer.",
    },
}

_DEFAULT_HINT = "Something unexpected happened, but I'll try to help."


_RETRY_SUGGESTIONS: dict[str, str] = {
    "timeout": "You could try asking again — sometimes things are just briefly slow.",
    "connection": "This is usually temporary. Try again in a moment.",
    "rate_limit": "I'm busy right now. Please wait a minute and try again.",
    "not_found": "Try rephrasing your question or asking about something else.",
    "data": "Could you rephrase that? I had trouble understanding the request.",
    "unknown": "Try asking your question in a different way, or try again shortly.",
}


# ---------------------------------------------------------------------------
# Error context builder
# ---------------------------------------------------------------------------


def build_error_context(node_name: str, error: Exception, state: dict) -> ErrorContext:
    """Build a structured error context from a node failure.

    This context flows through the LangGraph state and is available to
    the generate_response node for crafting natural error messages.
    """
    error_type = classify_error(error)

    # Get node-specific hint or fall back to default
    node_hints = _NODE_HINTS.get(node_name, {})
    user_hint = node_hints.get(error_type, _DEFAULT_HINT)

    # Track what data is available vs. unavailable
    available_data: list[str] = []
    unavailable_data: list[str] = []

    if state.get("user_profile"):
        available_data.append("profile")
    if state.get("conversation_history"):
        available_data.append("conversation_history")
    if state.get("acknowledgment_text"):
        available_data.append("acknowledgment")
    if state.get("planned_queries"):
        available_data.append("search_plan")

    query_results = state.get("query_results", {})
    if query_results:
        for table, results in query_results.items():
            if results:
                available_data.append(f"search:{table}")
            else:
                unavailable_data.append(f"search:{table}")

    # If this is a search node that failed, mark search as unavailable
    if node_name in ("execute_queries", "plan_queries") and not query_results:
        unavailable_data.append("search_results")

    return ErrorContext(
        failed_node=node_name,
        error_type=error_type,
        error_detail=str(error),
        user_hint=user_hint,
        degraded_results=True,
        available_data=available_data,
        unavailable_data=unavailable_data,
        can_retry=error_type in ("timeout", "connection", "rate_limit"),
        retry_suggestion=_RETRY_SUGGESTIONS.get(
            error_type, _RETRY_SUGGESTIONS["unknown"]
        ),
    )


# ---------------------------------------------------------------------------
# The decorator
# ---------------------------------------------------------------------------


def graceful_node(node_name: str, *, critical: bool = False) -> Callable:
    """Wrap a LangGraph node so it never crashes the pipeline.

    Args:
        node_name: Human-readable name for logging and error context.
        critical: If True and the node fails, the pipeline skips straight
                  to generate_response via force_response=True.
                  If False, the pipeline continues with degraded data.

    Usage::

        @graceful_node("fetch_data", critical=False)
        async def fetch_data_parallel(state: AssistantState) -> dict:
            ...
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(state: dict, *args: Any, **kwargs: Any) -> dict:
            try:
                return await func(state, *args, **kwargs)
            except Exception as e:
                logger.error(
                    "graceful_node.failure",
                    node=node_name,
                    critical=critical,
                    error_type=type(e).__name__,
                    error=str(e),
                    trace_id=state.get("trace_id", ""),
                    traceback=traceback.format_exc(),
                )

                error_context = build_error_context(node_name, e, state)

                # Build the partial-state update
                update: dict[str, Any] = {
                    "error_context": error_context,
                    "partial_failure": True,
                    "error": f"{node_name} failed: {e}",
                    "error_node": node_name,
                    "current_node": node_name,
                }

                if critical:
                    # Skip remaining nodes, go straight to generate_response
                    update["force_response"] = True

                return update

        return wrapper

    return decorator
