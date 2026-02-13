"""Node 3: Structured query planning via Claude Sonnet."""

import json
import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.llm_registry import get_llm_registry
from src.agent.nodes.error_wrapper import graceful_node
from src.agent.prompt_registry import get_prompt_registry
from src.agent.state import AssistantState
from src.services.faq_cache import get_faq_cache

logger = structlog.get_logger()


@graceful_node("plan_queries", critical=False)
async def plan_queries(state: AssistantState) -> dict:
    """Use Sonnet to produce a structured JSON search plan.

    Now uses RAM FAQCache for planning to avoid large state serialization.
    """
    logger.info("===== NODE 4: PLAN QUERIES =====")
    messages = state["messages"]
    user_message = str(messages[-1].content) if messages else ""
    profile = state.get("user_profile", {})
    history = state.get("conversation_history", [])
    user_context = state.get("user_context", {})

    # Get FAQ list from RAM cache (Fast, no I/O)
    faq_cache = get_faq_cache()
    faq_list = faq_cache.get_short_list()

    logger.info(
        "  [plan_queries] Building context for Sonnet...",
        user_message=str(user_message)[:200],
        has_profile=bool(profile),
        history_count=len(history),
        faq_count=len(faq_list),
    )

    context_parts = [f"User message: {user_message}"]
    if profile:
        context_parts.append(f"User profile: {json.dumps(profile, default=str)}")
    if history:
        recent = history[-5:]  # Last 5 messages for context
        context_parts.append(f"Recent conversation: {json.dumps(recent, default=str)}")

    if faq_list:
        context_parts.append(
            f"General FAQ Topics:\n{json.dumps(faq_list, default=str)}"
        )

    if user_context.get("conference_id"):
        context_parts.append(f"Conference ID: {user_context['conference_id']}")

    plan_prompt = "\n\n".join(context_parts)

    try:
        logger.info("  [plan_queries] Calling LLM to generate search plan...")
        registry = get_prompt_registry()
        llm = get_llm_registry().get_model("plan_queries")
        result = await llm.ainvoke(
            [
                SystemMessage(
                    content=registry.get("plan_queries"),
                    additional_kwargs={"cache_control": {"type": "ephemeral"}},
                ),
                HumanMessage(content=plan_prompt),
            ]
        )

        # Parse JSON from response
        content = str(result.content).strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        plan = json.loads(content)

        intent = plan.get("intent", "unknown")
        direct_response = plan.get("direct_response", False)
        faq_id = plan.get("faq_id")
        query_mode = plan.get("query_mode", "hybrid")
        planned_queries = plan.get("queries", [])

        # Profile detection result
        profile_update_data = plan.get("profile_update", {})
        needs_update = profile_update_data.get("needs_update", False)
        updates = profile_update_data.get("updates")

        logger.info(
            "===== NODE 4: PLAN QUERIES COMPLETE =====",
            intent=intent,
            direct_response=direct_response,
            needs_profile_update=needs_update,
            query_mode=query_mode,
            num_queries=len(planned_queries),
        )

        return {
            "intent": intent,
            "direct_response": direct_response,
            "faq_id": faq_id,
            "query_mode": query_mode,
            "planned_queries": planned_queries,
            "profile_needs_update": needs_update,
            "profile_updates": updates,
            "current_node": "plan_queries",
        }
    except Exception as e:
        logger.error("  [plan_queries] FAILED", error=str(e))
        return {
            "intent": "unknown",
            "direct_response": False,
            "faq_id": None,
            "query_mode": "hybrid",
            "planned_queries": [],
            "error": f"Plan failed: {e}",
            "current_node": "plan_queries",
        }
