"""Node 8: Haiku quality scoring (non-blocking, background)."""

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.llm_registry import get_llm_registry
from src.agent.prompt_registry import get_prompt_registry
from src.agent.state import AssistantState
from src.config import settings
from src.services.directus import get_directus_client

logger = structlog.get_logger()


async def evaluate(state: AssistantState) -> dict:
    """Score the generated response using Haiku.

    This runs after generate_response. The SSE 'done' event is sent
    before this node completes, so it doesn't block the user.
    Results are stored in Directus when available.
    """
    logger.info("===== NODE 8: EVALUATE (Background) =====")

    if not settings.evaluation_enabled:
        logger.info("  [evaluate] SKIPPED — evaluation disabled in config")
        return {
            "quality_score": None,
            "confidence_score": None,
            "current_node": "evaluate",
        }

    messages = state["messages"]
    user_message = messages[-1].content if messages else ""
    response_text = state.get("response_text", "")
    query_results = state.get("query_results", {})
    user_context = state.get("user_context", {})

    eval_prompt = (
        f"User question: {user_message}\n\n"
        f"Search results available: {json.dumps(query_results, default=str)[:2000]}\n\n"
        f"Assistant response: {response_text}"
    )

    quality_score = None
    confidence_score = None

    try:
        logger.info("  [evaluate] Calling LLM to score response quality...")
        registry = get_prompt_registry()
        llm = get_llm_registry().get_model("evaluate")
        result = await llm.ainvoke(
            [
                SystemMessage(
                    content=registry.get("evaluate"),
                    additional_kwargs={"cache_control": {"type": "ephemeral"}},
                ),
                HumanMessage(content=eval_prompt),
            ]
        )

        content = str(result.content).strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        scores = json.loads(content)
        quality_score = scores.get("quality_score")
        confidence_score = scores.get("confidence_score")

        logger.info(
            "===== NODE 8: EVALUATE COMPLETE =====",
            quality_score=quality_score,
            confidence_score=confidence_score,
        )

        # Store evaluation in Directus (fire-and-forget)
        conversation_id = user_context.get("conversation_id")
        message_id = user_context.get("message_id")
        if conversation_id and message_id and quality_score is not None:
            try:
                client = get_directus_client()
                await client.store_evaluation(
                    conversation_id, message_id, quality_score, confidence_score or 0.0
                )
            except Exception as e:
                logger.warning(
                    "  [evaluate] Failed to store evaluation in Directus", error=str(e)
                )

    except Exception as e:
        logger.warning("  [evaluate] Scoring FAILED", error=str(e))

    return {
        "quality_score": quality_score,
        "confidence_score": confidence_score,
        "current_node": "evaluate",
    }
