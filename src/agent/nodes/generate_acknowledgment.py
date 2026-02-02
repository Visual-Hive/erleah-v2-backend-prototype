"""Node: Generate contextual acknowledgment via Grok/xAI."""

import structlog

from src.agent.state import AssistantState
from src.services.grok import get_grok_client

logger = structlog.get_logger()


async def generate_acknowledgment(state: AssistantState) -> dict:
    """Generate a quick contextual acknowledgment using Grok.

    This runs early in the pipeline so the user gets immediate feedback
    while heavier processing (plan_queries, execute_queries) continues.
    """
    logger.info("generate_acknowledgment.start")
    messages = state["messages"]
    user_message = messages[-1].content if messages else ""
    user_profile = state.get("user_profile", {})

    grok = get_grok_client()
    ack_text = await grok.generate_acknowledgment(user_message, user_profile)

    logger.info("generate_acknowledgment.done", ack_length=len(ack_text))

    return {
        "acknowledgment_text": ack_text,
        "current_node": "generate_acknowledgment",
    }
