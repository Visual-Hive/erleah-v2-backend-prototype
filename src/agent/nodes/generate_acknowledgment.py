"""Node: Generate contextual acknowledgment via Grok/xAI."""

import structlog

from src.agent.nodes.error_wrapper import graceful_node
from src.agent.state import AssistantState
from src.services.grok import get_grok_client

logger = structlog.get_logger()


@graceful_node("generate_acknowledgment", critical=False)
async def generate_acknowledgment(state: AssistantState) -> dict:
    """Generate a quick contextual acknowledgment using Grok.

    This runs early in the pipeline so the user gets immediate feedback
    while heavier processing (plan_queries, execute_queries) continues.
    """
    logger.info("===== NODE 3: GENERATE ACKNOWLEDGMENT =====")
    messages = state["messages"]
    user_message = messages[-1].content if messages else ""
    user_profile = state.get("user_profile", {})

    logger.info(
        "  [acknowledgment] Calling Grok/xAI for quick acknowledgment...",
        user_message=str(user_message)[:100],
    )
    grok = get_grok_client()
    ack_text = await grok.generate_acknowledgment(str(user_message), user_profile)

    logger.info(
        "===== NODE 3: ACKNOWLEDGMENT COMPLETE =====",
        acknowledgment=ack_text,
    )

    return {
        "acknowledgment_text": ack_text,
        "current_node": "generate_acknowledgment",
    }
