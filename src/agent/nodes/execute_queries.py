"""Node 4: Parallel query execution via hybrid_search."""

import asyncio
from dataclasses import asdict

import structlog

from src.agent.nodes.error_wrapper import graceful_node
from src.agent.state import AssistantState
from src.search.faceted import hybrid_search, extract_display_name
from src.services.cache import get_cache_service, make_key

logger = structlog.get_logger()


@graceful_node("execute_queries", critical=False)
async def execute_queries(state: AssistantState) -> dict:
    """Execute all planned queries in parallel using hybrid_search.

    Each query maps directly to a hybrid_search call.
    Results are grouped by table name.
    """
    logger.info("===== NODE 5: EXECUTE QUERIES =====")
    planned = state.get("planned_queries", [])
    user_context = state.get("user_context", {})
    conference_id = user_context.get("conference_id", "")
    user_id = user_context.get("user_id", "")

    if not planned:
        logger.info("  [execute_queries] SKIPPED — no planned queries")
        return {"query_results": {}, "current_node": "execute_queries"}

    logger.info(
        "  [execute_queries] Executing %d queries in parallel...",
        len(planned),
    )
    for i, q in enumerate(planned):
        logger.info(
            "  [execute_queries] Query %d: table=%s mode=%s text='%s' limit=%d",
            i + 1,
            q.get("table", "?"),
            q.get("search_mode", "?"),
            str(q.get("query_text", ""))[:100],
            q.get("limit", 10),
        )

    cache = get_cache_service()

    async def _run_query(q: dict) -> tuple[str, list]:
        table = q.get("table", "sessions")
        search_mode = q.get("search_mode", "faceted")
        query_text = q.get("query_text", "")
        limit = q.get("limit", 10)
        use_faceted = search_mode == "faceted"

        # Cache query results (skip user-specific/profile queries)
        is_cacheable = not user_id or search_mode != "profile"
        cache_key = make_key(
            "query", table, query_text, search_mode, str(limit), conference_id
        )

        if is_cacheable:
            cached = await cache.get(cache_key)
            if cached is not None:
                logger.info(
                    "  [execute_queries] Cache HIT for %s query: '%s'",
                    table,
                    query_text[:50],
                )
                return table, cached

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
            if is_cacheable and result_dicts:
                await cache.set(cache_key, result_dicts, ttl=300)
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
