"""Node: Generate contextual acknowledgment via LLM."""

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.nodes.error_wrapper import graceful_node
from src.agent.llm_registry import get_llm_registry
from src.agent.prompt_registry import get_prompt_registry
from src.agent.state import AssistantState

logger = structlog.get_logger()


@graceful_node("generate_acknowledgment", critical=False)
async def generate_acknowledgment(state: AssistantState) -> dict:
    """Generate a quick contextual acknowledgment.

    This runs early in the pipeline so the user gets immediate feedback
    while heavier processing (plan_queries, execute_queries) continues.
    """
    logger.info("===== NODE 3: GENERATE ACKNOWLEDGMENT =====")
    messages = state["messages"]
    user_message = messages[-1].content if messages else ""
    user_profile = state.get("user_profile", {})

    logger.info(
        "  [acknowledgment] Generating quick acknowledgment...",
        user_message=str(user_message)[:100],
    )

    try:
        registry = get_prompt_registry()
        llm = get_llm_registry().get_model("acknowledgment")

        user_content = f"User message: {user_message}"
        if user_profile and user_profile.get("interests"):
            user_content += f"\nUser interests: {user_profile['interests']}"

        result = await llm.ainvoke(
            [
                SystemMessage(content=registry.get("acknowledgment")),
                HumanMessage(content=user_content),
            ]
        )
        ack_text = str(result.content).strip()
    except Exception as e:
        ack_text = "I'll help you with that."
        logger.warning(
            "  [acknowledgment] FAILED — using fallback",
            error=str(e),
            fallback=ack_text,
        )

    logger.info(
        "===== NODE 3: ACKNOWLEDGMENT COMPLETE =====",
        acknowledgment=ack_text,
    )

    return {
        "acknowledgment_text": ack_text,
        "current_node": "generate_acknowledgment",
    }