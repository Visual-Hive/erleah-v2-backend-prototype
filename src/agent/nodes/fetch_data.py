"""Node 1: Fetch user profile and conversation history in parallel."""

import asyncio
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
    """Fetch user profile and conversation history.

    FAQ/General Info is now handled by a global RAM cache to minimize latency.
    """
    user_context = state.get("user_context", {})
    user_id = user_context.get("user_id")
    conversation_id = user_context.get("conversation_id")
    start_time = asyncio.get_event_loop().time()

    logger.info(
        "===== NODE 1: FETCH DATA =====",
        user_id=user_id,
        conversation_id=conversation_id,
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
            return
        import uuid

        try:
            uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            logger.warning("  [fetch_data] Invalid UUID for user_id", user_id=user_id)
            return

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
            logger.warning("  [fetch_data] Profile fetch FAILED", error=str(e))

    async def _fetch_history():
        nonlocal history
        if not conversation_id:
            return
        import uuid

        try:
            uuid.UUID(str(conversation_id))
        except (ValueError, TypeError):
            logger.warning(
                "  [fetch_data] Invalid UUID for conversation_id",
                conversation_id=conversation_id,
            )
            return

        try:
            client = get_directus_client()
            history = await client.get_conversation_context(conversation_id)
        except Exception as e:
            logger.warning("  [fetch_data] History fetch FAILED", error=str(e))

    # Parallel fetch of ONLY dynamic user data
    await asyncio.gather(_fetch_profile(), _fetch_history())

    duration = asyncio.get_event_loop().time() - start_time
    logger.info("===== NODE 1: FETCH DATA COMPLETE =====", duration=f"{duration:.3f}s")

    return {
        "user_profile": profile,
        "conversation_history": history,
        "current_node": "fetch_data",
    }