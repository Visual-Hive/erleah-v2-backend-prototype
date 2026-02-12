"""Node 4: Parallel query execution via hybrid_search."""

import asyncio
from dataclasses import asdict

import structlog

from src.agent.state import AssistantState
from src.search.faceted import hybrid_search, extract_display_name
from src.services.cache import get_cache_service, make_key

logger = structlog.get_logger()


async def execute_queries(state: AssistantState) -> dict:
    """Execute all planned queries in parallel using hybrid_search.

    Implementation:
    1. Collect all unique query texts.
    2. Batch-embed them in one call to OpenAI/Azure (saves latency/RPM).
    3. Execute all table searches in parallel using pre-computed vectors.
    """
    logger.info("===== NODE 5: EXECUTE QUERIES =====")
    planned = state.get("planned_queries", [])
    user_context = state.get("user_context", {})
    conference_id = user_context.get("conference_id", "")

    if not planned:
        logger.info("  [execute_queries] SKIPPED — no planned queries")
        return {"query_results": {}, "current_node": "execute_queries"}

    # 1. Collect unique query texts for batching
    unique_texts = list(
        set(q.get("query_text", "") for q in planned if q.get("query_text"))
    )
    logger.info(
        "  [execute_queries] Batching %d unique queries from %d planned searches",
        len(unique_texts),
        len(planned),
    )

    # 2. Batch embed
    from src.services.embedding import get_embedding_service

    embedding_service = get_embedding_service()

    text_to_vector = {}
    if unique_texts:
        vectors = await embedding_service.embed_batch(unique_texts)
        text_to_vector = dict(zip(unique_texts, vectors))

    # 3. Execute searches in parallel
    async def _run_query(q: dict) -> tuple[str, list]:
        table = q.get("table", "sessions")
        search_mode = q.get("search_mode", "faceted")
        query_text = q.get("query_text", "")
        limit = q.get("limit", 10)
        use_faceted = search_mode == "faceted"

        vector = text_to_vector.get(query_text)

        try:
            logger.info(
                "  [execute_queries] Searching Qdrant: table=%s faceted=%s query='%s'",
                table,
                use_faceted,
                query_text[:80],
            )
            results = await hybrid_search(
                entity_type=table,
                query=query_text,
                conference_id=conference_id,
                use_faceted=use_faceted,
                limit=limit,
                query_vector=vector,
            )
            # Convert SearchResult dataclasses to dicts for serialization
            result_dicts = [asdict(r) for r in results]
            logger.info(
                "  [execute_queries] Results for %s: %d matches found",
                table,
                len(result_dicts),
            )
            for j, r in enumerate(result_dicts[:5]):
                display_name = extract_display_name(
                    r.get("payload", {}).get("name"),
                    r.get("payload", {}).get("description", ""),
                    r.get("entity_id", "?")[:12],
                )
                logger.info(
                    "    [execute_queries] #%d: %s (score=%.3f, facets=%d)",
                    j + 1,
                    display_name[:60],
                    r.get("total_score", 0),
                    r.get("facet_matches", 0),
                )
            return table, result_dicts
        except Exception as e:
            logger.warning(
                "  [execute_queries] Query FAILED: table=%s error=%s", table, str(e)
            )
            return table, []

    tasks = [_run_query(q) for q in planned]
    results_list = await asyncio.gather(*tasks)

    # Merge results by table (multiple queries may target the same table)
    query_results: dict[str, list] = {}
    for table, results in results_list:
        if table in query_results:
            query_results[table].extend(results)
        else:
            query_results[table] = results

    total = sum(len(v) for v in query_results.values())
    logger.info(
        "===== NODE 5: EXECUTE QUERIES COMPLETE =====",
        total_results=total,
        results_per_table={t: len(v) for t, v in query_results.items()},
    )

    return {"query_results": query_results, "current_node": "execute_queries"}
