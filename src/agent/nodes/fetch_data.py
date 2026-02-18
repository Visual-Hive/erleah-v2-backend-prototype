"""Node 1: Fetch user profile and conversation history in parallel."""

import asyncio
import structlog

from src.agent.nodes.error_wrapper import graceful_node
from src.agent.state import AssistantState
from src.services.conversation import get_conversation_service
from src.services.simulation import get_simulation_registry

logger = structlog.get_logger()


@graceful_node("fetch_data", critical=False)
async def fetch_data_parallel(state: AssistantState) -> dict:
    """Fetch conversation context for anonymous users (TASK-03).

    Uses ConversationService which caches in Redis (2 min TTL).
    Profile fetching is skipped — anonymous users only.
    """
    user_context = state.get("user_context", {})
    conversation_id = user_context.get("conversation_id")
    start_time = asyncio.get_event_loop().time()

    logger.info(
        "===== NODE 1: FETCH DATA =====",
        conversation_id=conversation_id,
    )

    # Simulation hook
    sim = get_simulation_registry()
    if sim.get("simulate_directus_failure"):
        logger.warning("  [fetch_data] SIMULATION: Directus failure triggered")
        raise ConnectionError("Simulated Directus failure (debug mode)")

    # Fetch conversation context (handles missing conversation_id gracefully)
    conv_context: dict = {
        "conversation_id": conversation_id,
        "message_count": 0,
        "is_first_message": True,
        "recent_messages": [],
        "referenced_entities": [],
        "summary": None,
    }

    if conversation_id:
        try:
            svc = get_conversation_service()
            conv_context = await svc.get_context(conversation_id)
        except Exception as exc:
            logger.warning("  [fetch_data] Conversation fetch failed", error=str(exc))

    duration = asyncio.get_event_loop().time() - start_time
    logger.info("===== NODE 1: FETCH DATA COMPLETE =====", duration=f"{duration:.3f}s")

    return {
        "conversation_context": conv_context,
        # Keep backward-compat fields so existing nodes don't break
        "user_profile": {},
        "conversation_history": conv_context.get("recent_messages", []),
        "profile_needs_update": False,
        "current_node": "fetch_data",
    }
