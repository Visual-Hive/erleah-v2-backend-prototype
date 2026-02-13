import httpx
import structlog
from typing import Any
from src.config import settings
from src.services.resilience import async_retry, get_circuit_breaker

logger = structlog.get_logger()


class DirectusClient:
    def __init__(self):
        self.base_url = settings.directus_url
        self.headers = {
            "Authorization": f"Bearer {settings.directus_api_key}",
            "Content-Type": "application/json",
        }
        self._client = httpx.AsyncClient(
            base_url=self.base_url, headers=self.headers, timeout=30.0
        )
        self._breaker = get_circuit_breaker("directus")

    # --- Conversation / Message Handling ---
    # Production Directus uses:
    #   Collection: "Message" (capital M, singular)
    #   Fields: "agent" (not "role"), "conversation" (not "conversation_id")
    #   No "status" or "metadata" fields on messages

    @async_retry(
        max_retries=2, base_delay=0.5, exceptions=(httpx.HTTPError, httpx.ConnectError)
    )
    async def get_conversation_context(
        self, conversation_id: str, limit: int = 10
    ) -> list[dict]:
        """Fetch recent messages for a conversation."""

        async def _fetch():
            response = await self._client.get(
                "/items/Message",
                params={
                    "filter[conversation][_eq]": conversation_id,
                    "sort": "-date_created",
                    "limit": limit,
                    "fields": "agent,messageText,date_created",
                },
            )
            response.raise_for_status()
            data = response.json().get("data", [])
            return list(reversed(data))  # Chronological order

        return await self._breaker.call(_fetch)

    async def create_message(
        self,
        conversation_id: str,
        role: str = "streamingAssistant",
        message_text: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create a message in Directus."""
        # Production schema uses 'agent' for role, 'messageText' for text
        payload = {
            "conversation": conversation_id,
            "agent": role,
            "messageText": message_text,
            "message_complete": False,
            "message_error": False,
        }

        response = await self._client.post("/items/Message", json=payload)
        response.raise_for_status()
        return response.json()["data"]

    async def update_message(self, message_id: str, updates: dict[str, Any]):
        """Update a message record."""
        # Map generic 'message_text' to 'messageText' if present
        if "message_text" in updates:
            updates["messageText"] = updates.pop("message_text")

        await self._client.patch(f"/items/Message/{message_id}", json=updates)

    async def create_assistant_message(self, conversation_id: str) -> str:
        """Create a placeholder message for the assistant."""
        response = await self._client.post(
            "/items/Message",
            json={
                "conversation": conversation_id,
                "agent": "streamingAssistant",
                "messageText": "",
            },
        )
        response.raise_for_status()
        return response.json()["data"]["id"]

    async def update_message_text(self, message_id: str, text: str):
        """Update text during streaming."""
        await self._client.patch(
            f"/items/Message/{message_id}", json={"messageText": text}
        )

    async def complete_message(
        self, message_id: str, final_text: str, metadata: dict[str, Any] | None = None
    ):
        """Mark message as completed with final text."""
        # Production has no "status" or "metadata" fields on Message
        # Just update the messageText
        payload: dict[str, Any] = {"messageText": final_text}
        await self._client.patch(f"/items/Message/{message_id}", json=payload)

    # --- User Profile ---
    # Production collection: "user_profile" (singular)

    @async_retry(
        max_retries=2, base_delay=0.5, exceptions=(httpx.HTTPError, httpx.ConnectError)
    )
    async def get_user_profile(self, user_id: str) -> dict[str, Any]:
        """Fetch user profile by ID."""

        async def _fetch():
            response = await self._client.get(
                f"/items/user_profile/{user_id}",
            )
            response.raise_for_status()
            return response.json().get("data", {})

        try:
            return await self._breaker.call(_fetch)
        except Exception as e:
            logger.warning(
                "Failed to fetch user profile", user_id=user_id, error=str(e)
            )
            return {}

    @async_retry(
        max_retries=2, base_delay=0.5, exceptions=(httpx.HTTPError, httpx.ConnectError)
    )
    async def update_user_profile(self, user_id: str, updates: dict[str, Any]) -> bool:
        """Update user profile fields."""

        async def _update():
            response = await self._client.patch(
                f"/items/user_profile/{user_id}",
                json=updates,
            )
            response.raise_for_status()
            return True

        try:
            return await self._breaker.call(_update)
        except Exception as e:
            logger.warning(
                "Failed to update user profile", user_id=user_id, error=str(e)
            )
            return False

    async def store_evaluation(
        self,
        conversation_id: str,
        message_id: str,
        quality_score: float,
        confidence_score: float,
    ) -> bool:
        """Store evaluation results. Production uses 'trace' collection."""
        try:
            response = await self._client.post(
                "/items/trace",
                json={
                    "conversation": conversation_id,
                    "message": message_id,
                    "quality_score": quality_score,
                    "confidence_score": confidence_score,
                },
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.warning("Failed to store evaluation", error=str(e))
            return False

    # --- Data Fetching (For Ingestion / RAG) ---
    # Production uses singular collection names and no conference_id filter
    # (single-conference instance)

    async def get_exhibitors(self, limit: int = 500, offset: int = 0) -> list[dict]:
        """Fetch exhibitors from production Directus."""
        res = await self._client.get(
            "/items/exhibitor",
            params={
                "limit": limit,
                "offset": offset,
                "fields": "*,vector_profile",
            },
        )
        res.raise_for_status()
        return res.json().get("data", [])

    async def get_sessions(self, limit: int = 500, offset: int = 0) -> list[dict]:
        """Fetch sessions from production Directus."""
        res = await self._client.get(
            "/items/session",
            params={
                "limit": limit,
                "offset": offset,
                "fields": "*",
            },
        )
        res.raise_for_status()
        return res.json().get("data", [])

    async def get_speakers(self, limit: int = 500, offset: int = 0) -> list[dict]:
        """Fetch speakers from production Directus."""
        res = await self._client.get(
            "/items/speaker",
            params={
                "limit": limit,
                "offset": offset,
                "fields": "*",
            },
        )
        res.raise_for_status()
        return res.json().get("data", [])

    async def get_user_profiles(self, limit: int = 500, offset: int = 0) -> list[dict]:
        """Fetch user profiles (attendees) from production Directus.
        Paginated — call multiple times with offset for large datasets.
        """
        res = await self._client.get(
            "/items/user_profile",
            params={
                "limit": limit,
                "offset": offset,
                "fields": "*,vector_profile",
            },
        )
        res.raise_for_status()
        return res.json().get("data", [])

    async def get_all_user_profiles(self) -> list[dict]:
        """Fetch ALL user profiles with pagination (handles 3500+ records)."""
        all_profiles: list[dict] = []
        offset = 0
        batch_size = 500
        while True:
            batch = await self.get_user_profiles(limit=batch_size, offset=offset)
            if not batch:
                break
            all_profiles.extend(batch)
            if len(batch) < batch_size:
                break
            offset += batch_size
            logger.info(
                "Fetched user profiles batch",
                offset=offset,
                total_so_far=len(all_profiles),
            )
        return all_profiles

    async def get_general_info(self, limit: int = 500) -> list[dict]:
        """Fetch general info / FAQ items."""
        res = await self._client.get(
            "/items/general_info",
            params={"limit": limit, "fields": "*"},
        )
        res.raise_for_status()
        return res.json().get("data", [])

    async def get_locations(self) -> list[dict]:
        """Fetch venue locations."""
        res = await self._client.get(
            "/items/location",
            params={"fields": "*"},
        )
        res.raise_for_status()
        return res.json().get("data", [])


# Singleton
_directus_client: DirectusClient | None = None


def get_directus_client() -> DirectusClient:
    global _directus_client
    if _directus_client is None:
        _directus_client = DirectusClient()
    return _directus_client
