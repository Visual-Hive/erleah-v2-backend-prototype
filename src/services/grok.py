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
        has_key = bool(settings.xai_api_key and settings.xai_api_key.strip())
        logger.info(
            "  [grok] GrokClient initialized",
            model=self._model,
            api_key_configured=has_key,
        )

    async def generate_acknowledgment(
        self, user_message: str, user_profile: dict | None = None
    ) -> str:
        """Generate a contextual acknowledgment. Returns fallback on any error."""
        import time as _time

        from src.agent.prompt_registry import get_prompt_registry

        start = _time.perf_counter()

        logger.info(
            "  [grok] generating acknowledgment",
            model=self._model,
            message_preview=user_message[:80],
            has_profile=bool(user_profile),
        )

        try:
            user_content = f"User message: {user_message}"
            if user_profile and user_profile.get("interests"):
                user_content += f"\nUser interests: {user_profile['interests']}"

            registry = get_prompt_registry()
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[
                    {"role": "system", "content": registry.get("acknowledgment")},
                    {"role": "user", "content": user_content},
                ],
                max_tokens=60,
                temperature=0.3,
            )
            result = (response.choices[0].message.content or "").strip()
            logger.info(
                "  [grok] acknowledgment generated",
                result=result[:100],
                duration=f"{_time.perf_counter() - start:.3f}s",
            )
            return result
        except Exception as e:
            fallback = "I'll help you with that."
            logger.warning(
                "  [grok] acknowledgment FAILED — using fallback",
                error=str(e),
                fallback=fallback,
                duration=f"{_time.perf_counter() - start:.3f}s",
            )
            return fallback


# Singleton
_grok_client: GrokClient | None = None


def get_grok_client() -> GrokClient:
    global _grok_client
    if _grok_client is None:
        _grok_client = GrokClient()
    return _grok_client
