import httpx
import structlog
from typing import Any
from src.config import settings

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

    # --- Conversation / Message Handling ---

    async def get_conversation_context(
        self, conversation_id: str, limit: int = 10
    ) -> list[dict]:
        """Fetch recent messages."""
        response = await self._client.get(
            "/items/messages",
            params={
                "filter[conversation_id][_eq]": conversation_id,
                "sort": "-date_created",
                "limit": limit,
                "fields": "role,messageText",
            },
        )
        response.raise_for_status()
        data = response.json().get("data", [])
        return list(reversed(data))  # Chronological order

    async def create_assistant_message(self, conversation_id: str) -> str:
        """Create a placeholder message for the assistant (status=streaming)."""
        response = await self._client.post(
            "/items/messages",
            json={
                "conversation_id": conversation_id,
                "role": "assistant",
                "messageText": "",
                "status": "streaming",
                "user_created": "public-user",
            },
        )
        response.raise_for_status()
        return response.json()["data"]["id"]

    async def update_message_text(self, message_id: str, text: str):
        """Update text during streaming."""
        await self._client.patch(
            f"/items/messages/{message_id}", json={"messageText": text}
        )

    async def complete_message(
        self, message_id: str, final_text: str, metadata: dict = None
    ):
        """Mark message as completed."""
        payload = {"messageText": final_text, "status": "completed"}
        if metadata:
            payload["metadata"] = metadata
        await self._client.patch(f"/items/messages/{message_id}", json=payload)

    # --- User Profile ---

    async def get_user_profile(self, user_id: str) -> dict[str, Any]:
        """Fetch user profile by ID."""
        try:
            response = await self._client.get(
                f"/items/user_profiles/{user_id}",
            )
            response.raise_for_status()
            return response.json().get("data", {})
        except Exception as e:
            logger.warning("Failed to fetch user profile", user_id=user_id, error=str(e))
            return {}

    async def update_user_profile(self, user_id: str, updates: dict[str, Any]) -> bool:
        """Update user profile fields."""
        try:
            response = await self._client.patch(
                f"/items/user_profiles/{user_id}",
                json=updates,
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.warning("Failed to update user profile", user_id=user_id, error=str(e))
            return False

    async def store_evaluation(
        self, conversation_id: str, message_id: str, quality_score: float, confidence_score: float
    ) -> bool:
        """Store evaluation results for a response."""
        try:
            response = await self._client.post(
                "/items/evaluations",
                json={
                    "conversation_id": conversation_id,
                    "message_id": message_id,
                    "quality_score": quality_score,
                    "confidence_score": confidence_score,
                },
            )
            response.raise_for_status()
            return True
        except Exception as e:
            logger.warning("Failed to store evaluation", error=str(e))
            return False

    # --- Data Fetching (For Ingestion or RAG) ---

    async def get_exhibitors(self, conference_id: str):
        res = await self._client.get(
            "/items/exhibitors", params={"filter[conference_id][_eq]": conference_id}
        )
        return res.json().get("data", [])

    async def get_sessions(self, conference_id: str):
        res = await self._client.get(
            "/items/sessions", params={"filter[conference_id][_eq]": conference_id}
        )
        return res.json().get("data", [])


# Singleton
_directus_client: DirectusClient | None = None


def get_directus_client() -> DirectusClient:
    global _directus_client
    if _directus_client is None:
        _directus_client = DirectusClient()
    return _directus_client
