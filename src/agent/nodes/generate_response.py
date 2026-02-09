"""Node 7: Claude Sonnet streaming response generation.

Includes error-aware prompt injection (Phase 2, TASK-01) and a last-resort
fallback so the user ALWAYS receives a coherent message, even if the LLM
is completely down.
"""

import json
import re

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.llm_registry import get_llm_registry
from src.agent.nodes.error_wrapper import classify_error
from src.agent.prompt_registry import get_prompt_registry
from src.agent.state import AssistantState

logger = structlog.get_logger()


# ---------------------------------------------------------------------------
# Last-resort fallback messages (used when even the LLM call fails)
# ---------------------------------------------------------------------------

LAST_RESORT_MESSAGES: dict[str, str] = {
    "timeout": (
        "I'm sorry, I'm running a bit slow right now. Could you try asking "
        "your question again in a moment? If the problem persists, try a "
        "simpler question."
    ),
    "connection": (
        "I'm having trouble connecting to my services right now. This is "
        "usually temporary — please try again in a minute or two."
    ),
    "rate_limit": (
        "I'm receiving a lot of questions right now and need a moment to "
        "catch up. Please try again in about a minute."
    ),
    "default": (
        "I ran into an unexpected issue processing your question. Please "
        "try again, and if the problem continues, try rephrasing your "
        "question. I'm here to help!"
    ),
}


def _extract_mentioned_ids(response_text: str, all_ids: list[str]) -> list[str]:
    """Extract only entity IDs that are actually mentioned in the response text."""
    mentioned = []
    for eid in all_ids:
        if eid in response_text:
            mentioned.append(eid)
    return mentioned


def _build_error_section(state: AssistantState) -> str:
    """Build error context section for the system prompt.

    Returns an empty string if there are no errors, or a formatted
    section that tells the LLM what went wrong.
    """
    error_context = state.get("error_context")
    if not error_context:
        return ""

    parts = ["\n\n## Current Error Context"]
    parts.append(f"A failure occurred in the '{error_context.get('failed_node', 'unknown')}' step.")
    parts.append(f"Issue type: {error_context.get('error_type', 'unknown')}")

    hint = error_context.get("user_hint")
    if hint:
        parts.append(f"Suggested response approach: {hint}")

    available = error_context.get("available_data", [])
    unavailable = error_context.get("unavailable_data", [])
    if available:
        parts.append(f"Data that IS available: {', '.join(available)}")
    if unavailable:
        parts.append(f"Data that is NOT available: {', '.join(unavailable)}")

    retry_suggestion = error_context.get("retry_suggestion")
    if retry_suggestion:
        parts.append(f"You may suggest: {retry_suggestion}")

    return "\n".join(parts)


async def generate_response(state: AssistantState) -> dict:
    """Generate the final user-facing response using Sonnet.

    This node is the one whose streaming tokens are forwarded to the client
    via SSE. The graph.astream_events() call filters for this node's output.

    If the LLM call itself fails, a hardcoded last-resort fallback message
    is returned so the user NEVER sees a dead-end.
    """
    logger.info("===== NODE 7: GENERATE RESPONSE =====")
    messages = state["messages"]
    user_message = messages[-1].content if messages else ""
    query_results = state.get("query_results", {})
    profile = state.get("user_profile", {})
    intent = state.get("intent", "unknown")
    history = state.get("conversation_history", [])
    has_error = state.get("partial_failure", False)

    # Log what data we're feeding into response generation
    total_results = sum(len(v) for v in query_results.values())
    logger.info(
        "  [generate_response] Preparing context for Sonnet",
        intent=intent,
        total_search_results=total_results,
        tables_with_results=[t for t, v in query_results.items() if v],
        has_profile=bool(profile),
        history_count=len(history),
        has_error=has_error,
    )

    # Build context for the LLM
    context_parts = [f"User question: {user_message}"]
    context_parts.append(f"Detected intent: {intent}")

    if profile:
        context_parts.append(f"User profile: {json.dumps(profile, default=str)}")

    if history:
        recent = history[-3:]
        context_parts.append(f"Recent conversation: {json.dumps(recent, default=str)}")

    # Collect all entity IDs from results
    all_entity_ids = []

    # Format search results
    if query_results:
        for table, results in query_results.items():
            if results:
                for r in results:
                    eid = r.get("entity_id")
                    if eid:
                        all_entity_ids.append(eid)
                context_parts.append(
                    f"\nSearch results for '{table}' ({len(results)} results):\n"
                    f"{json.dumps(results[:10], default=str, indent=2)}"
                )
            else:
                context_parts.append(f"\nNo results found for '{table}'.")
    else:
        context_parts.append("\nNo search results available.")

    generation_prompt = "\n\n".join(context_parts)

    # Build system prompt with error awareness if needed
    registry = get_prompt_registry()
    system_prompt = registry.get("generate_response")
    error_section = _build_error_section(state)
    if error_section:
        system_prompt += error_section

    try:
        # Use ainvoke (streaming is handled by astream_events at the graph level)
        logger.info(
            "  [generate_response] Calling LLM to generate user-facing response..."
        )
        llm = get_llm_registry().get_model("generate_response")
        result = await llm.ainvoke(
            [
                SystemMessage(
                    content=system_prompt,
                    additional_kwargs={"cache_control": {"type": "ephemeral"}},
                ),
                HumanMessage(content=generation_prompt),
            ]
        )

        response_text = str(result.content)

        # Extract only entity IDs that are actually mentioned in the response
        referenced_ids = _extract_mentioned_ids(response_text, all_entity_ids)

        logger.info(
            "===== NODE 7: GENERATE RESPONSE COMPLETE =====",
            response_length=len(response_text),
            response_preview=response_text[:200],
            referenced_entities=len(referenced_ids),
        )

        return {
            "response_text": response_text,
            "referenced_ids": referenced_ids,
            "current_node": "generate_response",
        }
    except Exception as e:
        # Last-resort fallback: LLM is completely down
        logger.error(
            "  [generate_response] FAILED — using last-resort fallback",
            error=str(e),
        )
        error_type = classify_error(e)
        fallback = LAST_RESORT_MESSAGES.get(
            error_type, LAST_RESORT_MESSAGES["default"]
        )
        return {
            "response_text": fallback,
            "referenced_ids": [],
            "error": f"Generation failed (fallback used): {e}",
            "current_node": "generate_response",
        }
