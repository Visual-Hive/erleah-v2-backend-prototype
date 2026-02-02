import structlog
from openai import AsyncOpenAI
from src.config import settings

logger = structlog.get_logger()


class EmbeddingService:
    """Service for generating text embeddings using OpenAI."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.embedding_model

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text."""
        try:
            # Normalize text
            text = text.replace("\n", " ")
            response = await self.client.embeddings.create(
                model=self.model,
                input=text,
            )
            return response.data[0].embedding
        except Exception as e:
            logger.error("embedding_failed", error=str(e))
            raise

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts (batch)."""
        try:
            # OpenAI allows batching
            # Clean texts
            cleaned_texts = [t.replace("\n", " ") for t in texts]
            response = await self.client.embeddings.create(
                model=self.model,
                input=cleaned_texts,
            )
            return [item.embedding for item in response.data]
        except Exception as e:
            logger.error("batch_embedding_failed", error=str(e))
            raise


# Singleton instance
_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
