"""Node 7: Claude Sonnet streaming response generation."""

import json
import structlog
import time
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.llm_registry import get_llm_registry
from src.agent.prompt_registry import get_prompt_registry
from src.agent.state import AssistantState
from src.services.faq_cache import get_faq_cache

logger = structlog.get_logger()


def _extract_mentioned_ids(response_text: str, all_ids: list[str]) -> list[str]:
    """Extract only entity IDs that are actually mentioned in the response text."""
    mentioned = []
    for eid in all_ids:
        if eid in response_text:
            mentioned.append(eid)
    return mentioned


async def generate_response(state: AssistantState) -> dict:
    """Generate the final user-facing response using Sonnet.

    Uses RAM FAQCache for direct responses to stay fast and avoid large state.
    """
    logger.info("===== NODE 7: GENERATE RESPONSE =====")
    messages = state["messages"]
    user_message = messages[-1].content if messages else ""
    query_results = state.get("query_results", {})
    profile = state.get("user_profile", {})
    intent = state.get("intent", "unknown")
    history = state.get("conversation_history", [])
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

    try:
        logger.info("  [generate_response] Calling LLM to generate response...")
        registry = get_prompt_registry()
        llm = get_llm_registry().get_model("generate_response")
        result = await llm.ainvoke(
            [
                SystemMessage(
                    content=registry.get("generate_response"),
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
        logger.error("  [generate_response] FAILED", error=str(e))
        return {
            "response_text": "I'm sorry, I encountered an error. Please try again.",
            "referenced_ids": [],
            "error": f"Generation failed: {e}",
            "current_node": "generate_response",
        }
