import asyncio
import structlog
from typing import Any
from src.services.directus import get_directus_client

logger = structlog.get_logger()


class FAQCache:
    """In-memory cache for General Info (FAQ) to avoid Directus latency."""

    _instance = None

    def __init__(self):
        self._all_faqs: list[dict[str, Any]] = []
        self._faq_map: dict[str, dict[str, Any]] = {}
        self._short_list: list[dict[str, str]] = []
        self._last_updated: float = 0
        self._lock = asyncio.Lock()

    @classmethod
    def get_instance(cls) -> "FAQCache":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def refresh(self):
        """Fetch fresh data from Directus and update RAM cache."""
        async with self._lock:
            try:
                t0 = asyncio.get_event_loop().time()
                client = get_directus_client()
                # Fetch only necessary fields to reduce payload
                data = await client.get_general_info()

                self._all_faqs = data
                self._faq_map = {item["id"]: item for item in data}
                self._short_list = [
                    {"id": item["id"], "question": item["question"]} for item in data
                ]
                self._last_updated = t0

                logger.info(
                    "  [faq_cache] RAM cache updated",
                    count=len(data),
                    duration=f"{asyncio.get_event_loop().time() - t0:.3f}s",
                )
            except Exception as e:
                logger.error("  [faq_cache] Refresh FAILED", error=str(e))

    def get_short_list(self) -> list[dict[str, str]]:
        """Return list of questions and IDs for planning."""
        return self._short_list

    def get_answer(self, faq_id: str) -> dict[str, Any] | None:
        """Return full FAQ item by ID."""
        return self._faq_map.get(faq_id)


_faq_cache = FAQCache.get_instance()


def get_faq_cache() -> FAQCache:
    return _faq_cache
