"""Node 1: Parallel fetch of user profile, conversation history, and profile update detection."""

import asyncio
import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.llm import sonnet
from src.agent.nodes.error_wrapper import graceful_node
from src.agent.prompts import PROFILE_DETECT_SYSTEM
from src.agent.state import AssistantState
from src.services.cache import get_cache_service, make_key
from src.services.directus import get_directus_client
from src.services.simulation import get_simulation_registry

logger = structlog.get_logger()


@graceful_node("fetch_data", critical=False)
async def fetch_data_parallel(state: AssistantState) -> dict:
    """Fetch user profile and conversation history in parallel.

    Also detects whether the user's message contains profile-relevant info.
    Gracefully handles missing Directus (returns empty defaults).
    """
    user_context = state.get("user_context", {})
    user_id = user_context.get("user_id")
    conversation_id = user_context.get("conversation_id")
    messages = state["messages"]
    user_message = messages[-1].content if messages else ""

    logger.info(
        "===== NODE 1: FETCH DATA =====",
        user_id=user_id,
        conversation_id=conversation_id,
        user_message=str(user_message)[:200],
    )

    # Check simulation flags
    sim = get_simulation_registry()
    if sim.get("simulate_directus_failure"):
        logger.warning("  [fetch_data] 🐛 SIMULATION: Directus failure triggered")
        raise ConnectionError("Simulated Directus failure (debug mode)")

    # Parallel fetch: profile + history
    profile: dict = {}
    history: list[dict] = []
    cache = get_cache_service()

    async def _fetch_profile():
        nonlocal profile
        if not user_id:
            logger.info("  [fetch_data] No user_id provided, skipping profile fetch")
            return
        # Check cache first (5 min TTL)
        cache_key = make_key("profile", user_id)
        cached = await cache.get(cache_key)
        if cached is not None:
            profile = cached
            logger.info("  [fetch_data] Profile loaded from cache", user_id=user_id)
            return
        try:
            client = get_directus_client()
            profile = await client.get_user_profile(user_id)
            await cache.set(cache_key, profile, ttl=300)
            logger.info(
                "  [fetch_data] Profile fetched from Directus",
                user_id=user_id,
                profile_keys=list(profile.keys()) if profile else [],
            )
        except Exception as e:
            logger.warning("  [fetch_data] Profile fetch FAILED", error=str(e))

    async def _fetch_history():
        nonlocal history
        if not conversation_id:
            logger.info("  [fetch_data] No conversation_id, skipping history fetch")
            return
        try:
            client = get_directus_client()
            history = await client.get_conversation_context(conversation_id)
            logger.info(
                "  [fetch_data] Conversation history loaded", message_count=len(history)
            )
        except Exception as e:
            logger.warning("  [fetch_data] History fetch FAILED", error=str(e))

    await asyncio.gather(_fetch_profile(), _fetch_history())

    # Detect profile update need via LLM (only if we have a profile)
    profile_needs_update = False
    if profile and user_message:
        logger.info(
            "  [fetch_data] Checking if user message contains profile updates via LLM..."
        )
        try:
            detect_prompt = (
                f"Current profile:\n{json.dumps(profile, default=str)}\n\n"
                f"User message:\n{user_message}"
            )
            result = await sonnet.ainvoke(
                [
                    SystemMessage(
                        content=PROFILE_DETECT_SYSTEM,
                        additional_kwargs={"cache_control": {"type": "ephemeral"}},
                    ),
                    HumanMessage(content=detect_prompt),
                ]
            )
            parsed = json.loads(str(result.content))
            profile_needs_update = parsed.get("needs_update", False)
            logger.info(
                "  [fetch_data] Profile update detection result",
                needs_update=profile_needs_update,
            )
        except Exception as e:
            logger.warning("  [fetch_data] Profile detect FAILED", error=str(e))

    logger.info(
        "===== NODE 1: FETCH DATA COMPLETE =====",
        has_profile=bool(profile),
        history_messages=len(history),
        profile_needs_update=profile_needs_update,
    )

    return {
        "user_profile": profile,
        "conversation_history": history,
        "profile_needs_update": profile_needs_update,
        "current_node": "fetch_data",
    }
