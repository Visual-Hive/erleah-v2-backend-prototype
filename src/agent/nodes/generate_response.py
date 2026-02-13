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


def _condense_search_result(result: dict, entity_type: str) -> dict:
    """Extract key fields from a search result based on entity type.
    
    Creates a condensed version of search results to reduce prompt size
    while keeping essential information for response generation.
    
    Args:
        result: A search result dict from execute_queries, with structure:
            {
                "entity_id": str,
                "entity_type": str,
                "total_score": float,
                "facet_matches": int,
                "payload": { ... actual entity data ... }
            }
        entity_type: The type of entity (exhibitors, sessions, speakers, attendees)
    """
    # The actual data is nested in the 'payload' field
    payload = result.get("payload", {})
    
    condensed = {
        "name": payload.get("name") or payload.get("title") or payload.get("company_name") or "Unknown",
        "entity_id": result.get("entity_id"),
        "score": result.get("total_score"),  # Include relevance score
    }
    
    # Add entity-specific fields from payload, checking if they exist
    if entity_type == "exhibitors":
        if payload.get("category"):
            condensed["category"] = payload["category"]
        if payload.get("description"):
            condensed["description"] = payload["description"][:200]
        if payload.get("booth"):
            condensed["booth"] = payload["booth"]
        if payload.get("website"):
            condensed["website"] = payload["website"]
            
    elif entity_type == "sessions":
        if payload.get("speakers"):
            condensed["speakers"] = payload["speakers"]
        if payload.get("start_time"):
            condensed["time"] = payload["start_time"]
        elif payload.get("time"):
            condensed["time"] = payload["time"]
        if payload.get("end_time"):
            condensed["end_time"] = payload["end_time"]
        if payload.get("location"):
            condensed["location"] = payload["location"]
        if payload.get("track"):
            condensed["track"] = payload["track"]
        if payload.get("description"):
            condensed["description"] = payload["description"][:150]
            
    elif entity_type == "speakers":
        if payload.get("company"):
            condensed["company"] = payload["company"]
        if payload.get("title"):
            condensed["title"] = payload["title"]
        if payload.get("bio"):
            condensed["bio"] = payload["bio"][:150]
        if payload.get("sessions"):
            condensed["sessions"] = payload["sessions"]
            
    elif entity_type == "attendees":
        if payload.get("company"):
            condensed["company"] = payload["company"]
        if payload.get("role"):
            condensed["role"] = payload["role"]
        if payload.get("interests"):
            # Top 5 interests to keep prompt small
            interests = payload["interests"]
            if isinstance(interests, list):
                condensed["interests"] = interests[:5]
            else:
                condensed["interests"] = interests
        if payload.get("looking_for"):
            condensed["looking_for"] = payload["looking_for"][:100]
    
    return condensed


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

    # Collect all entity IDs from search results and build condensed context
    all_entity_ids = []
    if query_results:
        for table, results in query_results.items():
            if results:
                for r in results:
                    eid = r.get("entity_id")
                    if eid:
                        all_entity_ids.append(eid)
                
                # Use the helper function to condense results based on entity type
                condensed_results = [
                    _condense_search_result(r, table) for r in results[:5]
                ]
                
                context_parts.append(
                    f"\nSearch results for '{table}' ({len(results)} found, showing {len(condensed_results)}):\n"
                    f"{json.dumps(condensed_results, default=str, indent=2)}"
                )
            else:
                context_parts.append(f"\nNo results found for '{table}'.")

    generation_prompt = "\n\n".join(context_parts)
    
    # Log prompt size for debugging latency issues
    prompt_tokens_estimate = len(generation_prompt) // 4  # Rough estimate: ~4 chars per token
    logger.info(
        "  [generate_response] Prompt built",
        prompt_length_chars=len(generation_prompt),
        estimated_tokens=prompt_tokens_estimate,
        num_search_results=total_results,
    )

    # Build system prompt with error awareness if needed
    registry = get_prompt_registry()
    system_prompt = registry.get("generate_response")
    error_section = _build_error_section(state)
    if error_section:
        system_prompt += error_section

    try:
        # Use astream() for true streaming - emits on_chat_model_stream events
        # that the graph level captures and forwards to SSE clients.
        # We collect chunks here for the final response_text.
        registry = get_llm_registry()
        llm = registry.get_model("generate_response")
        model_config = registry.get_node_config("generate_response")

        # Build messages - only Anthropic supports cache_control
        messages = [HumanMessage(content=generation_prompt)]
        if model_config.provider == "anthropic":
            # Anthropic: use cache_control for prompt caching
            messages = [
                SystemMessage(
                    content=system_prompt,
                    additional_kwargs={"cache_control": {"type": "ephemeral"}},
                ),
                HumanMessage(content=generation_prompt),
            ]
        else:
            # Other providers: include system as first message (OpenAI-compatible)
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=generation_prompt),
            ]

        logger.info(
            "  [generate_response] Starting LLM stream...",
            model=f"{model_config.provider}/{model_config.model_id}",
            display_name=model_config.display_name,
        )

        t0 = time.perf_counter()
        first_chunk_time = None
        chunk_count = 0
        full_response = ""

        async for chunk in llm.astream(messages):
            # Each chunk is an AIMessageChunk with .content
            content = chunk.content if hasattr(chunk, 'content') else str(chunk)
            if isinstance(content, str) and content:
                full_response += content
                chunk_count += 1
                if first_chunk_time is None:
                    first_chunk_time = time.perf_counter()
                    logger.info(
                        "  [generate_response] First token received",
                        time_to_first_token=f"{first_chunk_time - t0:.2f}s",
                    )

        duration = time.perf_counter() - t0
        response_text = full_response

        logger.info(
            "  [generate_response] LLM stream completed",
            model=f"{model_config.provider}/{model_config.model_id}",
            duration_seconds=f"{duration:.2f}s",
            total_chunks=chunk_count,
            time_to_first_token=f"{first_chunk_time - t0:.2f}s" if first_chunk_time else "N/A",
            response_length=len(response_text),
        )
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