"""Node 1: Parallel fetch of user profile, conversation history, and profile update detection."""

import asyncio
import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.llm import sonnet
from src.agent.prompts import PROFILE_DETECT_SYSTEM
from src.agent.state import AssistantState
from src.services.cache import get_cache_service, make_key
from src.services.directus import get_directus_client

logger = structlog.get_logger()


async def fetch_data_parallel(state: AssistantState) -> dict:
    """Fetch user profile and conversation history in parallel.

    Also detects whether the user's message contains profile-relevant info.
    Gracefully handles missing Directus (returns empty defaults).
    """
    logger.info("fetch_data_parallel.start")
    user_context = state.get("user_context", {})
    user_id = user_context.get("user_id")
    conversation_id = user_context.get("conversation_id")
    messages = state["messages"]
    user_message = messages[-1].content if messages else ""

    # Parallel fetch: profile + history
    profile: dict = {}
    history: list[dict] = []
    cache = get_cache_service()

    async def _fetch_profile():
        nonlocal profile
        if not user_id:
            return
        # Check cache first (5 min TTL)
        cache_key = make_key("profile", user_id)
        cached = await cache.get(cache_key)
        if cached is not None:
            profile = cached
            return
        try:
            client = get_directus_client()
            profile = await client.get_user_profile(user_id)
            await cache.set(cache_key, profile, ttl=300)
        except Exception as e:
            logger.warning("fetch_profile.failed", error=str(e))

    async def _fetch_history():
        nonlocal history
        if not conversation_id:
            return
        try:
            client = get_directus_client()
            history = await client.get_conversation_context(conversation_id)
        except Exception as e:
            logger.warning("fetch_history.failed", error=str(e))

    await asyncio.gather(_fetch_profile(), _fetch_history())

    # Detect profile update need via LLM (only if we have a profile)
    profile_needs_update = False
    if profile and user_message:
        try:
            detect_prompt = (
                f"Current profile:\n{json.dumps(profile, default=str)}\n\n"
                f"User message:\n{user_message}"
            )
            result = await sonnet.ainvoke(
                [
                    SystemMessage(content=PROFILE_DETECT_SYSTEM, additional_kwargs={"cache_control": {"type": "ephemeral"}}),
                    HumanMessage(content=detect_prompt),
                ]
            )
            parsed = json.loads(result.content)
            profile_needs_update = parsed.get("needs_update", False)
        except Exception as e:
            logger.warning("profile_detect.failed", error=str(e))

    logger.info(
        "fetch_data_parallel.done",
        has_profile=bool(profile),
        history_len=len(history),
        profile_needs_update=profile_needs_update,
    )

    return {
        "user_profile": profile,
        "conversation_history": history,
        "profile_needs_update": profile_needs_update,
        "current_node": "fetch_data",
    }
