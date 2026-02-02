"""Multi-faceted search implementation with weighted scoring and paired matching."""

import time

import structlog
from collections import defaultdict
from typing import Literal, Dict, List, Any
from dataclasses import dataclass

from src.services.qdrant import get_qdrant_service
from src.services.embedding import get_embedding_service
from src.search.facet_config import load_facet_config
from src.monitoring.metrics import (
    SEARCH_RESULTS, FACETED_SEARCH_SCORE, FACETED_SEARCH_DURATION,
    FACETS_MATCHED, FACET_PAIR_SIMILARITY,
)

logger = structlog.get_logger()

EntityType = Literal["sessions", "exhibitors", "speakers", "attendees"]

MIN_FACET_VALUE_LENGTH = 10


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
    user_profile_facets: dict[str, str] | None = None,
    filters: dict[str, Any] | None = None,
    score_threshold: float | None = None,
) -> List[SearchResult]:
    """
    Search using the multi-faceted strategy with weighted scoring.

    For attendees with user_profile_facets, uses paired matching:
    user's products_i_want_to_buy → target's products_i_want_to_sell, etc.
    """
    start_time = time.perf_counter()

    qdrant = get_qdrant_service()
    embedding_service = get_embedding_service()

    # Load facet config for this entity type
    facet_configs = load_facet_config()
    entity_config = facet_configs.get(entity_type)

    # Determine search strategy
    if entity_type == "attendees" and user_profile_facets and entity_config:
        # Paired matching: search each user facet against its complementary target facet
        result = await _paired_faceted_search(
            entity_type=entity_type,
            conference_id=conference_id,
            user_profile_facets=user_profile_facets,
            entity_config=entity_config,
            limit=limit,
        )
    else:
        # Standard faceted search (exhibitors, sessions, speakers)
        query_vector = await embedding_service.embed_text(query)

        search_kwargs = dict(
            entity_type=entity_type,
            query_vector=query_vector,
            conference_id=conference_id,
            facet_key=None,  # Search all facets
            limit=limit * 5,
        )
        if score_threshold is not None:
            search_kwargs["score_threshold"] = score_threshold
        raw_results = await qdrant.search_faceted(**search_kwargs)

        result = _aggregate_and_score(raw_results, entity_config, entity_type, limit)

    duration = time.perf_counter() - start_time
    FACETED_SEARCH_DURATION.labels(entity_type=entity_type).observe(duration)
    return result


async def _paired_faceted_search(
    entity_type: str,
    conference_id: str,
    user_profile_facets: dict[str, str],
    entity_config: Any,
    limit: int,
) -> List[SearchResult]:
    """Attendee-specific paired matching: buyer↔seller facet search."""
    import asyncio

    qdrant = get_qdrant_service()
    embedding_service = get_embedding_service()

    all_raw_results = []

    async def _search_pair(user_facet_key: str, user_facet_text: str):
        """Embed user facet text and search against the paired target facet."""
        target_facet = entity_config.get_pair(user_facet_key)
        if not target_facet:
            target_facet = user_facet_key  # Self-pair fallback

        query_vector = await embedding_service.embed_text(user_facet_text)
        results = await qdrant.search_faceted(
            entity_type=entity_type,
            query_vector=query_vector,
            conference_id=conference_id,
            facet_key=target_facet,
            limit=limit * 3,
        )
        return user_facet_key, results

    # Search all user facets in parallel, skipping short values
    tasks = [
        _search_pair(fk, ft)
        for fk, ft in user_profile_facets.items()
        if ft and len(ft) >= MIN_FACET_VALUE_LENGTH
    ]
    pair_results = await asyncio.gather(*tasks)

    # Collect all results, annotating with which user facet matched
    entities: Dict[str, Any] = defaultdict(lambda: {"facet_scores": {}, "payload": None})

    for user_facet_key, results in pair_results:
        weight = entity_config.get_weight(user_facet_key)
        for hit in results:
            e_id = hit.payload.get("entity_id")
            if not e_id:
                continue

            # Record pair similarity metric
            FACET_PAIR_SIMILARITY.labels(facet_key=user_facet_key).observe(hit.score)

            # Score this hit weighted by the user facet importance
            current = entities[e_id]["facet_scores"].get(user_facet_key, 0)
            if hit.score > current:
                entities[e_id]["facet_scores"][user_facet_key] = hit.score

            if not entities[e_id]["payload"]:
                entities[e_id]["payload"] = hit.payload

    # Calculate composite score with adaptive breadth denominator
    non_empty_facets = entity_config.count_non_empty_facets(user_profile_facets)
    total_facets = non_empty_facets if non_empty_facets > 0 else entity_config.total_facets
    final_results = []

    for e_id, data in entities.items():
        facet_scores = data["facet_scores"]
        matched_facets = len(facet_scores)

        breadth = matched_facets / total_facets
        weighted_sum = 0.0
        weight_sum = 0.0
        for fk, score in facet_scores.items():
            w = entity_config.get_weight(fk)
            weighted_sum += score * w
            weight_sum += w
        depth = weighted_sum / weight_sum if weight_sum > 0 else 0.0

        composite_score = (breadth * 0.4 + depth * 0.6) * 10

        FACETED_SEARCH_SCORE.observe(composite_score)
        FACETS_MATCHED.observe(matched_facets)

        final_results.append(
            SearchResult(
                entity_id=e_id,
                entity_type=entity_type,
                total_score=composite_score,
                facet_matches=matched_facets,
                payload=data["payload"],
            )
        )

    final_results.sort(key=lambda x: x.total_score, reverse=True)
    result = final_results[:limit]

    SEARCH_RESULTS.labels(table=entity_type, mode="paired_faceted").observe(len(result))
    return result


def _aggregate_and_score(
    raw_results: list,
    entity_config: Any,
    entity_type: str,
    limit: int,
) -> List[SearchResult]:
    """Aggregate raw Qdrant results by entity ID and compute composite score."""
    entities: Dict[str, Any] = defaultdict(lambda: {"facet_scores": {}, "payload": None})

    for hit in raw_results:
        e_id = hit.payload.get("entity_id")
        if not e_id:
            continue

        facet_key = hit.payload.get("facet_key", "unknown")
        current = entities[e_id]["facet_scores"].get(facet_key, 0)
        if hit.score > current:
            entities[e_id]["facet_scores"][facet_key] = hit.score

        if not entities[e_id]["payload"]:
            entities[e_id]["payload"] = hit.payload

    total_facets = entity_config.total_facets if entity_config else 4
    final_results = []

    for e_id, data in entities.items():
        facet_scores = data["facet_scores"]
        matched_facets = len(facet_scores)

        breadth = matched_facets / total_facets

        if entity_config:
            weighted_sum = 0.0
            weight_sum = 0.0
            for fk, score in facet_scores.items():
                w = entity_config.get_weight(fk)
                weighted_sum += score * w
                weight_sum += w
            depth = weighted_sum / weight_sum if weight_sum > 0 else 0.0
        else:
            depth = sum(facet_scores.values()) / matched_facets if matched_facets else 0.0

        composite_score = (breadth * 0.4 + depth * 0.6) * 10

        FACETED_SEARCH_SCORE.observe(composite_score)
        FACETS_MATCHED.observe(matched_facets)

        final_results.append(
            SearchResult(
                entity_id=e_id,
                entity_type=entity_type,
                total_score=composite_score,
                facet_matches=matched_facets,
                payload=data["payload"],
            )
        )

    final_results.sort(key=lambda x: x.total_score, reverse=True)
    result = final_results[:limit]

    SEARCH_RESULTS.labels(table=entity_type, mode="faceted").observe(len(result))
    return result


async def hybrid_search(
    entity_type: EntityType,
    query: str,
    conference_id: str,
    use_faceted: bool = True,
    limit: int = 10,
    user_profile_facets: dict[str, str] | None = None,
    filters: dict[str, Any] | None = None,
    score_threshold: float | None = None,
) -> List[SearchResult]:
    """Router for choosing between Master Search (Specific) vs Faceted Search (Vague)."""

    if use_faceted:
        return await faceted_search(
            entity_type, query, conference_id, limit, user_profile_facets, filters,
            score_threshold=score_threshold,
        )

    # Fallback to Master collection (Simple vector search)
    qdrant = get_qdrant_service()
    embedding = get_embedding_service()
    query_vector = await embedding.embed_text(query)

    search_kwargs = dict(
        collection_name=f"{entity_type}_master",
        query_vector=query_vector,
        conference_id=conference_id,
        limit=limit,
    )
    if score_threshold is not None:
        search_kwargs["score_threshold"] = score_threshold
    raw = await qdrant.search(**search_kwargs)

    result = [
        SearchResult(
            entity_id=r.payload.get("entity_id"),
            entity_type=entity_type,
            total_score=r.score,
            facet_matches=1,
            payload=r.payload,
        )
        for r in raw
    ]

    SEARCH_RESULTS.labels(table=entity_type, mode="master").observe(len(result))
    return result
