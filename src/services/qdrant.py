import structlog
from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Distance, VectorParams, PointStruct

from src.config import settings

logger = structlog.get_logger()

# Defined in FACET_DEFINITIONS.md
COLLECTIONS = {
    "sessions_master": "sessions_master",
    "sessions_facets": "sessions_facets",
    "exhibitors_master": "exhibitors_master",
    "exhibitors_facets": "exhibitors_facets",
    "speakers_master": "speakers_master",
    "speakers_facets": "speakers_facets",
}


class QdrantService:
    def __init__(self):
        self.client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=30,
        )
        self.vector_size = 1536  # OpenAI text-embedding-3-small

    async def ensure_collections(self) -> None:
        """Create collections if they don't exist."""
        for name in COLLECTIONS.values():
            if not await self.client.collection_exists(name):
                await self.client.create_collection(
                    collection_name=name,
                    vectors_config=VectorParams(
                        size=self.vector_size,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"Created collection: {name}")

    async def upsert_points(
        self, collection_name: str, points: list
    ) -> None:
        """Upsert points into a collection."""
        await self.client.upsert(
            collection_name=collection_name,
            points=points,
        )
        logger.info(f"Upserted {len(points)} points into {collection_name}")

    async def search(
        self,
        collection_name: str,
        query_vector: list[float],
        conference_id: str,
        limit: int = 10,
        score_threshold: float = 0.4,
        filter_conditions: dict | None = None,
    ) -> list[models.ScoredPoint]:
        """Base search method."""

        # Base filter: Must match conference_id
        must_conditions = [
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

    async def search_faceted(
        self,
        entity_type: str,
        query_vector: list[float],
        conference_id: str,
        facet_key: str | None = None,  # If None, search ALL facets
        limit: int = 20,
    ) -> list[models.ScoredPoint]:
        """Wrapper for searching facet collections."""
        collection = f"{entity_type}_facets"
        filters = {"facet_key": facet_key} if facet_key else None

        return await self.search(
            collection_name=collection,
            query_vector=query_vector,
            conference_id=conference_id,
            limit=limit,
            score_threshold=0.3,  # Facets might have lower individual scores
            filter_conditions=filters,
        )


# Singleton
_qdrant_service: QdrantService | None = None


def get_qdrant_service() -> QdrantService:
    global _qdrant_service
    if _qdrant_service is None:
        _qdrant_service = QdrantService()
    return _qdrant_service
