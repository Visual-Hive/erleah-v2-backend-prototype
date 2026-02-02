"""Node 2: Conditional profile update via Claude."""

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.llm import sonnet
from src.agent.prompts import PROFILE_UPDATE_SYSTEM
from src.agent.state import AssistantState
from src.services.cache import get_cache_service, make_key
from src.services.directus import get_directus_client

logger = structlog.get_logger()


async def update_profile(state: AssistantState) -> dict:
    """Update the user profile if profile_needs_update is True.

    Uses Sonnet to merge new information into the existing profile,
    then persists the update to Directus.
    """
    logger.info("update_profile.start")
    user_context = state.get("user_context", {})
    user_id = user_context.get("user_id")
    profile = state.get("user_profile", {})
    messages = state["messages"]
    user_message = messages[-1].content if messages else ""

    if not user_id or not profile:
        logger.info("update_profile.skip", reason="no user_id or profile")
        return {"profile_updates": None, "current_node": "update_profile"}

    try:
        update_prompt = (
            f"Current profile:\n{json.dumps(profile, default=str)}\n\n"
            f"User message:\n{user_message}\n\n"
            f"Merge any new profile-relevant information from the message into the profile."
        )
        result = await sonnet.ainvoke(
            [
                SystemMessage(content=PROFILE_UPDATE_SYSTEM, additional_kwargs={"cache_control": {"type": "ephemeral"}}),
                HumanMessage(content=update_prompt),
            ]
        )
        updated_profile = json.loads(result.content)

        # Persist to Directus
        client = get_directus_client()
        await client.update_user_profile(user_id, updated_profile)

        # Invalidate profile cache
        cache = get_cache_service()
        await cache.delete(make_key("profile", user_id))

        logger.info("update_profile.done", updates=updated_profile)
        return {
            "profile_updates": updated_profile,
            "user_profile": updated_profile,
            "current_node": "update_profile",
        }
    except Exception as e:
        logger.warning("update_profile.failed", error=str(e))
        return {"profile_updates": None, "current_node": "update_profile"}
