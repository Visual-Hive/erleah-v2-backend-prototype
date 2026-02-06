import structlog
from openai import AsyncOpenAI
from src.config import settings
from src.services.cache import get_cache_service, make_key
from src.services.resilience import async_retry, get_circuit_breaker

logger = structlog.get_logger()


class EmbeddingService:
    """Service for generating text embeddings using OpenAI."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.embedding_model
        self._breaker = get_circuit_breaker("openai_embedding")
        logger.info(
            "  [embedding] EmbeddingService initialized",
            model=self.model,
        )

    async def embed_text(self, text: str) -> list[float]:
        """Generate embedding for a single text. Cached for 1 hour."""
        import time as _time

        start = _time.perf_counter()
        text_preview = text[:80] + "..." if len(text) > 80 else text

        # Check cache first (1 hour TTL)
        cache = get_cache_service()
        cache_key = make_key("emb", self.model, text)
        cached = await cache.get(cache_key, cache_type="embedding")
        if cached is not None:
            logger.info(
                "  [embedding] cache HIT",
                text_preview=text_preview,
                dimensions=len(cached),
                duration=f"{_time.perf_counter() - start:.3f}s",
            )
            return cached

        try:
            logger.info(
                "  [embedding] cache MISS — calling OpenAI",
                text_preview=text_preview,
                model=self.model,
            )
            embedding = await self._embed_with_retry(text)
            await cache.set(cache_key, embedding, ttl=3600)
            logger.info(
                "  [embedding] generated + cached",
                dimensions=len(embedding),
                duration=f"{_time.perf_counter() - start:.3f}s",
            )
            return embedding
        except Exception as e:
            logger.error(
                "  [embedding] FAILED",
                text_preview=text_preview,
                error=str(e),
                duration=f"{_time.perf_counter() - start:.3f}s",
            )
            raise

    @async_retry(max_retries=2, base_delay=1.0, exceptions=(Exception,))
    async def _embed_with_retry(self, text: str) -> list[float]:
        """Embed text with retry and circuit breaker."""

        async def _do_embed():
            cleaned = text.replace("\n", " ")
            response = await self.client.embeddings.create(
                model=self.model,
                input=cleaned,
            )
            return response.data[0].embedding

        return await self._breaker.call(_do_embed)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generate embeddings for multiple texts (batch)."""
        import time as _time

        start = _time.perf_counter()
        logger.info(
            "  [embedding] batch embedding started",
            batch_size=len(texts),
            model=self.model,
            first_text_preview=texts[0][:60] + "..." if texts else "empty",
        )
        try:
            # OpenAI allows batching
            # Clean texts
            cleaned_texts = [t.replace("\n", " ") for t in texts]
            response = await self.client.embeddings.create(
                model=self.model,
                input=cleaned_texts,
            )
            result = [item.embedding for item in response.data]
            logger.info(
                "  [embedding] batch complete",
                batch_size=len(texts),
                dimensions=len(result[0]) if result else 0,
                duration=f"{_time.perf_counter() - start:.3f}s",
            )
            return result
        except Exception as e:
            logger.error(
                "  [embedding] batch FAILED",
                batch_size=len(texts),
                error=str(e),
                duration=f"{_time.perf_counter() - start:.3f}s",
            )
            raise


# Singleton instance
_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
