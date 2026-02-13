"""Node 7: Claude Sonnet streaming response generation.

Includes error-aware prompt injection (Phase 2, TASK-01) and a last-resort
fallback so the user ALWAYS receives a coherent message, even if the LLM
is completely down.
"""

import json
import structlog
import time
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.llm_registry import get_llm_registry
from src.agent.nodes.error_wrapper import classify_error
from src.agent.prompt_registry import get_prompt_registry
from src.agent.state import AssistantState
from src.services.faq_cache import get_faq_cache

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

    Uses RAM FAQCache for direct responses to stay fast and avoid large state.
    """
    logger.info("===== NODE 7: GENERATE RESPONSE =====")
    messages = state["messages"]
    user_message = messages[-1].content if messages else ""
    query_results = state.get("query_results", {})
    profile = state.get("user_profile", {})
    intent = state.get("intent", "unknown")
    history = state.get("conversation_history", [])
    has_error = state.get("partial_failure", False)
    direct_response = state.get("direct_response", False)
    faq_id = state.get("faq_id")

    # Handle direct response from RAM FAQ cache
    faq_context = ""
    if direct_response and faq_id:
        t0 = time.perf_counter()
        faq_cache = get_faq_cache()
        matching_faq = faq_cache.get_answer(faq_id)

        if matching_faq:
            duration = time.perf_counter() - t0
            logger.info(
                "  [generate_response] [FAST PATH] Found matching FAQ in RAM",
                faq_id=faq_id,
                search_duration=f"{duration:.4f}s",
            )
            faq_context = f"\nRelevant General FAQ Entry:\nQuestion: {matching_faq['question']}\nAnswer: {matching_faq['answer']}\n"

    # Log what data we're feeding into response generation
    total_results = sum(len(v) for v in query_results.values())
    logger.info(
        "  [generate_response] Preparing context for Sonnet",
        intent=intent,
        direct_response=direct_response,
        total_search_results=total_results,
        has_profile=bool(profile),
        history_count=len(history),
        has_error=has_error,
    )

    # Build context for the LLM
    context_parts = [f"User question: {user_message}", f"Detected intent: {intent}"]

    if faq_context:
        context_parts.append(faq_context)

    if profile:
        context_parts.append(f"User profile: {json.dumps(profile, default=str)}")

    if history:
        recent = history[-3:]
        context_parts.append(f"Recent conversation: {json.dumps(recent, default=str)}")

    # Collect all entity IDs from search results
    all_entity_ids = []
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
        referenced_ids = _extract_mentioned_ids(response_text, all_entity_ids)

        logger.info(
            "===== NODE 7: GENERATE RESPONSE COMPLETE =====",
            response_length=len(response_text),
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