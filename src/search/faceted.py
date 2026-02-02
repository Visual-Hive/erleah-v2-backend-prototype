"""Multi-faceted search implementation with weighted scoring."""

import structlog
from collections import defaultdict
from typing import Literal, Dict, List, Any
from dataclasses import dataclass

from src.services.qdrant import get_qdrant_service
from src.services.embedding import get_embedding_service
from src.search.facet_config import load_facet_config

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
    Search using the multi-faceted strategy with weighted scoring.
    Instead of searching one vector, we search multiple facet vectors and aggregate.
    """
    qdrant = get_qdrant_service()
    embedding_service = get_embedding_service()

    # Load facet config for this entity type
    facet_configs = load_facet_config()
    entity_config = facet_configs.get(entity_type)

    # 1. Embed user query
    query_vector = await embedding_service.embed_text(query)

    # 2. Search ALL facets for this entity type
    raw_results = await qdrant.search_faceted(
        entity_type=entity_type,
        query_vector=query_vector,
        conference_id=conference_id,
        facet_key=None,  # Search all facets
        limit=limit * 5,
    )

    # 3. Aggregate results by Entity ID, tracking per-facet scores
    entities: Dict[str, Any] = defaultdict(lambda: {"facet_scores": {}, "payload": None})

    for hit in raw_results:
        e_id = hit.payload.get("entity_id")
        if not e_id:
            continue

        facet_key = hit.payload.get("facet_key", "unknown")
        # Keep the best score per facet for each entity
        current = entities[e_id]["facet_scores"].get(facet_key, 0)
        if hit.score > current:
            entities[e_id]["facet_scores"][facet_key] = hit.score

        if not entities[e_id]["payload"]:
            entities[e_id]["payload"] = hit.payload

    # 4. Calculate Composite Score with weighted scoring
    total_facets = entity_config.total_facets if entity_config else 4
    final_results = []

    for e_id, data in entities.items():
        facet_scores = data["facet_scores"]
        matched_facets = len(facet_scores)

        # Breadth: fraction of total facets matched
        breadth = matched_facets / total_facets

        # Depth: weighted average of (similarity * facet_weight)
        if entity_config:
            weighted_sum = 0.0
            weight_sum = 0.0
            for fk, score in facet_scores.items():
                w = entity_config.get_weight(fk)
                weighted_sum += score * w
                weight_sum += w
            depth = weighted_sum / weight_sum if weight_sum > 0 else 0.0
        else:
            # Fallback: simple average
            depth = sum(facet_scores.values()) / matched_facets if matched_facets else 0.0

        # Composite score on 0-10 scale
        composite_score = (breadth * 0.4 + depth * 0.6) * 10

        final_results.append(
            SearchResult(
                entity_id=e_id,
                entity_type=entity_type,
                total_score=composite_score,
                facet_matches=matched_facets,
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
