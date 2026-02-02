import structlog
from openai import AsyncOpenAI
from src.config import settings
from src.services.cache import get_cache_service, make_key

logger = structlog.get_logger()


class EmbeddingService:
    """Service for generating text embeddings using OpenAI."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.embedding_model

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text. Cached for 1 hour."""
        # Check cache first (1 hour TTL)
        cache = get_cache_service()
        cache_key = make_key("emb", self.model, text)
        cached = await cache.get(cache_key)
        if cached is not None:
            return cached

        try:
            # Normalize text
            text = text.replace("\n", " ")
            response = await self.client.embeddings.create(
                model=self.model,
                input=text,
            )
            embedding = response.data[0].embedding
            await cache.set(cache_key, embedding, ttl=3600)
            return embedding
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
