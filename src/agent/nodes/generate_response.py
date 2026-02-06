"""Node 7: Claude Sonnet streaming response generation."""

import json
import re

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.llm import sonnet
from src.agent.prompts import GENERATE_RESPONSE_SYSTEM
from src.agent.state import AssistantState

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

    This node is the one whose streaming tokens are forwarded to the client
    via SSE. The graph.astream_events() call filters for this node's output.
    """
    logger.info("===== NODE 7: GENERATE RESPONSE =====")
    messages = state["messages"]
    user_message = messages[-1].content if messages else ""
    query_results = state.get("query_results", {})
    profile = state.get("user_profile", {})
    intent = state.get("intent", "unknown")
    history = state.get("conversation_history", [])

    # Log what data we're feeding into response generation
    total_results = sum(len(v) for v in query_results.values())
    logger.info(
        "  [generate_response] Preparing context for Sonnet",
        intent=intent,
        total_search_results=total_results,
        tables_with_results=[t for t, v in query_results.items() if v],
        has_profile=bool(profile),
        history_count=len(history),
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

    try:
        # Use ainvoke (streaming is handled by astream_events at the graph level)
        logger.info(
            "  [generate_response] Calling Sonnet to generate user-facing response..."
        )
        result = await sonnet.ainvoke(
            [
                SystemMessage(
                    content=GENERATE_RESPONSE_SYSTEM,
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
        logger.error("  [generate_response] FAILED", error=str(e))
        return {
            "response_text": "I'm sorry, I encountered an error generating a response. Please try again.",
            "referenced_ids": [],
            "error": f"Generation failed: {e}",
            "current_node": "generate_response",
        }
