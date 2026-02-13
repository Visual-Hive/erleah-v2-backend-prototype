import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Condition, Distance, VectorParams, PointStruct

from src.config import settings
from src.services.resilience import async_retry, get_circuit_breaker

logger = structlog.get_logger()

# Defined in FACET_DEFINITIONS.md — includes attendees
COLLECTIONS = {
    "sessions_master": "sessions_master",
    "sessions_facets": "sessions_facets",
    "exhibitors_master": "exhibitors_master",
    "exhibitors_facets": "exhibitors_facets",
    "speakers_master": "speakers_master",
    "speakers_facets": "speakers_facets",
    "attendees_master": "attendees_master",
    "attendees_facets": "attendees_facets",
}


class QdrantService:
    def __init__(self):
        self.client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=30,
        )
        self.vector_size = (
            settings.vector_size
        )  # From config (3072 for text-embedding-3-large)
        self._breaker = get_circuit_breaker("qdrant")
        logger.info(
            "  [qdrant] QdrantService initialized",
            url=settings.qdrant_url[:50] + "..."
            if len(settings.qdrant_url) > 50
            else settings.qdrant_url,
            vector_size=self.vector_size,
        )

    async def ensure_collections(self) -> None:
        """Create collections and payload indices if they don't exist."""
        logger.info(
            "  [qdrant] Ensuring collections and indices exist", total=len(COLLECTIONS)
        )
        for name in COLLECTIONS.values():
            if not await self.client.collection_exists(name):
                await self.client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(
                        size=self.vector_size,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"  [qdrant] Created collection: {name}")

            # Create Payload Index for conference_id (REQUIRED for filtering)
            await self.client.create_payload_index(
                collection_name=name,
                field_name="conference_id",
                field_schema=models.PayloadSchemaType.KEYWORD,
            )

            # Create Payload Index for facet_key in facet collections
            if "facets" in name:
                await self.client.create_payload_index(
                    collection_name=name,
                    field_name="facet_key",
                    field_schema=models.PayloadSchemaType.KEYWORD,
                )

        logger.info("  [qdrant] Collections and indices are READY")

    async def upsert_points(self, collection_name: str, points: list) -> None:
        """Upsert points into a collection."""
        await self.client.upsert(
            collection_name=collection_name,
            points=points,
        )
        logger.info(
            "  [qdrant] Upserted points",
            collection=collection_name,
            count=len(points),
        )

    @async_retry(max_retries=2, base_delay=0.5, exceptions=(Exception,))
    async def search(
        self,
        collection_name: str,
        query_vector: list[float],
        conference_id: str,
        limit: int = 10,
        score_threshold: float = 0.4,
        filter_conditions: dict | None = None,
    ) -> list[models.ScoredPoint]:
        """Base search method with retry and circuit breaker."""
        import time as _time

        search_start = _time.perf_counter()

        logger.info(
            "  [qdrant] search started",
            collection=collection_name,
            conference_id=conference_id,
            limit=limit,
            score_threshold=score_threshold,
            filters=filter_conditions or "none",
        )

        async def _do_search():
            # Base filter: Must match conference_id
            must_conditions: list[Condition] = [
                models.FieldCondition(
                    key="conference_id",
                    match=models.MatchValue(value=conference_id),
                )
            ]

            # Additional filters (e.g., facet_key)
            if filter_conditions:
                for key, value in filter_conditions.items():
                    must_conditions.append(
                        models.FieldCondition(
                            key=key,
                            match=models.MatchValue(value=value),
                        )
                    )

            result = await self.client.query_points(
                collection_name=collection_name,
                query=query_vector,
                query_filter=models.Filter(must=must_conditions),
                limit=limit,
                score_threshold=score_threshold,
            )
            return result.points

        results = await self._breaker.call(_do_search)
        duration = _time.perf_counter() - search_start

        top_scores = [f"{r.score:.3f}" for r in results[:3]] if results else []
        logger.info(
            "  [qdrant] search complete",
            collection=collection_name,
            results=len(results),
            top_3_scores=top_scores,
            duration=f"{duration:.3f}s",
        )
        return results

    async def search_faceted(
        self,
        entity_type: str,
        query_vector: list[float],
        conference_id: str,
        facet_key: str | None = None,  # If None, search ALL facets
        limit: int = 20,
        score_threshold: float = 0.1,  # Lowered default for multi-faceted matching
    ) -> list[models.ScoredPoint]:
        """Wrapper for searching facet collections."""
        # Ensure collection name is plural to match ingestion script
        plural = entity_type if entity_type.endswith("s") else f"{entity_type}s"
        collection = f"{plural}_facets"
        filters = {"facet_key": facet_key} if facet_key else None

        logger.info(
            "  [qdrant] search_faceted",
            entity_type=entity_type,
            collection=collection,
            facet_key=facet_key or "ALL",
            limit=limit,
            score_threshold=score_threshold,
        )

        return await self.search(
            collection_name=collection,
            query_vector=query_vector,
            conference_id=conference_id,
            limit=limit,
            score_threshold=score_threshold,
            filter_conditions=filters,
        )


# Singleton
_qdrant_service: QdrantService | None = None


def get_qdrant_service() -> QdrantService:
    global _qdrant_service
    if _qdrant_service is None:
        _qdrant_service = QdrantService()
    return _qdrant_service
