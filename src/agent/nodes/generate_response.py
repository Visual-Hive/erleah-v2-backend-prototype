"""Node 7: Claude Sonnet streaming response generation."""

import json

import structlog

from src.agent.llm import sonnet
from src.agent.prompts import GENERATE_RESPONSE_SYSTEM
from src.agent.state import AssistantState

logger = structlog.get_logger()


async def generate_response(state: AssistantState) -> dict:
    """Generate the final user-facing response using Sonnet.

    This node is the one whose streaming tokens are forwarded to the client
    via SSE. The graph.astream_events() call filters for this node's output.
    """
    logger.info("generate_response.start")
    messages = state["messages"]
    user_message = messages[-1].content if messages else ""
    query_results = state.get("query_results", {})
    profile = state.get("user_profile", {})
    intent = state.get("intent", "unknown")
    history = state.get("conversation_history", [])

    # Build context for the LLM
    context_parts = [f"User question: {user_message}"]
    context_parts.append(f"Detected intent: {intent}")

    if profile:
        context_parts.append(f"User profile: {json.dumps(profile, default=str)}")

    if history:
        recent = history[-3:]
        context_parts.append(f"Recent conversation: {json.dumps(recent, default=str)}")

    # Format search results
    if query_results:
        for table, results in query_results.items():
            if results:
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
        result = await sonnet.ainvoke(
            [
                {"role": "system", "content": GENERATE_RESPONSE_SYSTEM},
                {"role": "user", "content": generation_prompt},
            ]
        )

        response_text = result.content

        # Extract referenced entity IDs from results
        referenced_ids = []
        for results in query_results.values():
            for r in results:
                eid = r.get("entity_id")
                if eid:
                    referenced_ids.append(eid)

        logger.info("generate_response.done", response_length=len(response_text))

        return {
            "response_text": response_text,
            "referenced_ids": referenced_ids,
            "current_node": "generate_response",
        }
    except Exception as e:
        logger.error("generate_response.failed", error=str(e))
        return {
            "response_text": "I'm sorry, I encountered an error generating a response. Please try again.",
            "referenced_ids": [],
            "error": f"Generation failed: {e}",
            "current_node": "generate_response",
        }
