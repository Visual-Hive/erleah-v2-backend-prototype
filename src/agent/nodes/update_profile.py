"""Node 2: Conditional profile update via Claude."""

import json

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.llm import sonnet
from src.agent.prompt_registry import get_prompt_registry
from src.agent.state import AssistantState
from src.services.cache import get_cache_service, make_key
from src.services.directus import get_directus_client

logger = structlog.get_logger()


async def update_profile(state: AssistantState) -> dict:
    """Update the user profile if profile_needs_update is True.

    Uses Sonnet to merge new information into the existing profile,
    then persists the update to Directus.
    """
    logger.info("===== NODE 2: UPDATE PROFILE =====")
    user_context = state.get("user_context", {})
    user_id = user_context.get("user_id")
    profile = state.get("user_profile", {})
    messages = state["messages"]
    user_message = messages[-1].content if messages else ""

    if not user_id or not profile:
        logger.info("  [update_profile] SKIPPED — no user_id or empty profile")
        return {"profile_updates": None, "current_node": "update_profile"}

    try:
        logger.info("  [update_profile] Merging new info into profile via Sonnet...")
        update_prompt = (
            f"Current profile:\n{json.dumps(profile, default=str)}\n\n"
            f"User message:\n{user_message}\n\n"
            f"Merge any new profile-relevant information from the message into the profile."
        )
        registry = get_prompt_registry()
        result = await sonnet.ainvoke(
            [
                SystemMessage(
                    content=registry.get("profile_update"),
                    additional_kwargs={"cache_control": {"type": "ephemeral"}},
                ),
                HumanMessage(content=update_prompt),
            ]
        )
        updated_profile = json.loads(str(result.content))

        # Persist to Directus
        client = get_directus_client()
        await client.update_user_profile(user_id, updated_profile)

        # Invalidate profile cache
        cache = get_cache_service()
        await cache.delete(make_key("profile", user_id))

        logger.info(
            "===== NODE 2: UPDATE PROFILE COMPLETE =====",
            updated_keys=list(updated_profile.keys()),
        )
        return {
            "profile_updates": updated_profile,
            "user_profile": updated_profile,
            "current_node": "update_profile",
        }
    except Exception as e:
        logger.warning("  [update_profile] FAILED", error=str(e))
        return {"profile_updates": None, "current_node": "update_profile"}
