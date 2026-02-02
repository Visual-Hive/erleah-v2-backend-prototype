"""Multi-faceted search implementation."""

import structlog
from collections import defaultdict
from typing import Literal, Dict, List, Any
from dataclasses import dataclass

from src.services.qdrant import get_qdrant_service
from src.services.embedding import get_embedding_service

logger = structlog.get_logger()

EntityType = Literal["sessions", "exhibitors", "speakers"]


@dataclass
class SearchResult:
    entity_id: str
    entity_type: str
    total_score: float
    facet_matches: int
    payload: dict


async def faceted_search(
    entity_type: EntityType,
    query: str,
    conference_id: str,
    limit: int = 10,
) -> List[SearchResult]:
    """
    Search using the multi-faceted strategy.
    Instead of searching one vector, we search multiple facet vectors and aggregate.
    """
    qdrant = get_qdrant_service()
    embedding_service = get_embedding_service()

    # 1. Embed user query
    query_vector = await embedding_service.embed_text(query)

    # 2. Search ALL facets for this entity type
    # We ask for more results (limit * 5) to allow aggregation logic to work
    raw_results = await qdrant.search_faceted(
        entity_type=entity_type,
        query_vector=query_vector,
        conference_id=conference_id,
        facet_key=None,  # Search all facets
        limit=limit * 5,
    )

    # 3. Aggregate results by Entity ID
    entities: Dict[str, Any] = defaultdict(lambda: {"scores": [], "payload": None})

    for hit in raw_results:
        e_id = hit.payload.get("entity_id")
        if not e_id:
            continue

        entities[e_id]["scores"].append(hit.score)
        if not entities[e_id]["payload"]:
            entities[e_id]["payload"] = hit.payload

    # 4. Calculate Composite Score
    # Score = (Avg Similarity * 0.6) + (Match Bonus based on # facets matched * 0.4)
    final_results = []

    for e_id, data in entities.items():
        scores = data["scores"]
        num_matches = len(scores)
        avg_score = sum(scores) / num_matches

        # Cap bonus at 4 matches (diminishing returns)
        match_bonus = min(num_matches / 4.0, 1.0)

        composite_score = (avg_score * 0.6) + (match_bonus * 0.4)

        final_results.append(
            SearchResult(
                entity_id=e_id,
                entity_type=entity_type,
                total_score=composite_score,
                facet_matches=num_matches,
                payload=data["payload"],
            )
        )

    # 5. Sort and Limit
    final_results.sort(key=lambda x: x.total_score, reverse=True)
    return final_results[:limit]


async def hybrid_search(
    entity_type: EntityType,
    query: str,
    conference_id: str,
    use_faceted: bool = True,  # True for vague queries, False for specific
    limit: int = 10,
) -> List[SearchResult]:
    """Router for choosing between Master Search (Specific) vs Faceted Search (Vague)."""

    if use_faceted:
        return await faceted_search(entity_type, query, conference_id, limit)

    # Fallback to Master collection (Simple vector search)
    qdrant = get_qdrant_service()
    embedding = get_embedding_service()
    query_vector = await embedding.embed_text(query)

    raw = await qdrant.search(
        collection_name=f"{entity_type}_master",
        query_vector=query_vector,
        conference_id=conference_id,
        limit=limit,
    )

    return [
        SearchResult(
            entity_id=r.payload.get("entity_id"),
            entity_type=entity_type,
            total_score=r.score,
            facet_matches=1,
            payload=r.payload,
        )
        for r in raw
    ]
