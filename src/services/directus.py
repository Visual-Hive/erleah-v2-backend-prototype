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
