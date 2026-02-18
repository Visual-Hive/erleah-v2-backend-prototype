"""TASK-03: Conversation context service with Redis caching."""

import structlog

from src.services.cache import get_cache_service, make_key
from src.services.directus import get_directus_client

logger = structlog.get_logger()

MAX_HISTORY_MESSAGES = 20
CONTEXT_WINDOW_MESSAGES = 10
CACHE_TTL = 120  # 2 min — new messages arrive frequently


class ConversationService:
    """Fetch and cache conversation context for anonymous users."""

    async def get_context(self, conversation_id: str) -> dict:
        """Return conversation context dict, using Redis cache when possible."""
        cache = get_cache_service()
        cache_key = make_key("conv", conversation_id)

        cached = await cache.get(cache_key)
        if cached is not None:
            logger.debug("conversation_cache_hit", conversation_id=conversation_id)
            return cached

        messages: list[dict] = []
        try:
            client = get_directus_client()
            messages = await client.get_conversation_context(
                conversation_id, limit=MAX_HISTORY_MESSAGES
            )
        except Exception as exc:
            logger.warning(
                "conversation_fetch_failed",
                conversation_id=conversation_id,
                error=str(exc),
            )

        context = self._build_context(conversation_id, messages)

        try:
            await cache.set(cache_key, context, ttl=CACHE_TTL)
        except Exception:
            pass  # Cache failure is non-fatal

        logger.info(
            "conversation_context_built",
            conversation_id=conversation_id,
            message_count=context["message_count"],
        )
        return context

    async def invalidate(self, conversation_id: str) -> None:
        """Remove cached context so the next request fetches fresh history."""
        cache = get_cache_service()
        cache_key = make_key("conv", conversation_id)
        try:
            await cache.delete(cache_key)
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_context(self, conversation_id: str, messages: list[dict]) -> dict:
        recent = messages[-CONTEXT_WINDOW_MESSAGES:]
        return {
            "conversation_id": conversation_id,
            "message_count": len(messages),
            "is_first_message": len(messages) <= 1,
            "recent_messages": self._format_messages(recent),
            "referenced_entities": self._extract_referenced_ids(messages),
            "summary": None,
        }

    @staticmethod
    def _format_messages(messages: list[dict]) -> list[dict]:
        return [
            {
                "role": m.get("role", "user"),
                "text": m.get("messageText", ""),
                "timestamp": m.get("date_created", ""),
            }
            for m in messages
        ]

    @staticmethod
    def _extract_referenced_ids(messages: list[dict]) -> list[str]:
        ids: list[str] = []
        for m in messages:
            if m.get("role") == "assistant":
                meta = m.get("metadata") or {}
                ids.extend(meta.get("referenced_ids", []))
        return list(dict.fromkeys(ids))  # deduplicated, order-preserving


_service: ConversationService | None = None


def get_conversation_service() -> ConversationService:
    global _service
    if _service is None:
        _service = ConversationService()
    return _service
