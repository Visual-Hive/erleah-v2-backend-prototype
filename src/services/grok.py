"""Grok/xAI client for fast acknowledgment generation."""

import structlog
from openai import AsyncOpenAI

from src.config import settings

logger = structlog.get_logger()

ACKNOWLEDGMENT_SYSTEM = """\
You are a friendly conference assistant. Generate a brief 1-2 sentence acknowledgment \
of the user's message. Be contextual and warm. Do NOT answer their question — just \
acknowledge you received it and will help. Keep it under 30 words."""


class GrokClient:
    """xAI Grok client for fast acknowledgment messages."""

    def __init__(self) -> None:
        self._client = AsyncOpenAI(
            api_key=settings.xai_api_key,
            base_url="https://api.x.ai/v1",
        )
        self._model = settings.xai_model

    async def generate_acknowledgment(
        self, user_message: str, user_profile: dict | None = None
    ) -> str:
        """Generate a contextual acknowledgment. Returns fallback on any error."""
        try:
            user_content = f"User message: {user_message}"
            if user_profile and user_profile.get("interests"):
                user_content += f"\nUser interests: {user_profile['interests']}"

            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": ACKNOWLEDGMENT_SYSTEM},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=60,
                temperature=0.7,
            )
            return response.choices[0].message.content.strip()
        except Exception as e:
            logger.warning("grok.acknowledgment_failed", error=str(e))
            return "I'll help you with that."


# Singleton
_grok_client: GrokClient | None = None


def get_grok_client() -> GrokClient:
    global _grok_client
    if _grok_client is None:
        _grok_client = GrokClient()
    return _grok_client
