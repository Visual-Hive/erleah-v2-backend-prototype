"""Node 4: Parallel query execution via hybrid_search."""

import asyncio
from dataclasses import asdict

import structlog

from src.agent.state import AssistantState
from src.search.faceted import hybrid_search
from src.services.cache import get_cache_service, make_key

logger = structlog.get_logger()


async def execute_queries(state: AssistantState) -> dict:
    """Execute all planned queries in parallel using hybrid_search.

    Each query maps directly to a hybrid_search call.
    Results are grouped by table name.
    """
    logger.info("execute_queries.start")
    planned = state.get("planned_queries", [])
    user_context = state.get("user_context", {})
    conference_id = user_context.get("conference_id", "")
    user_id = user_context.get("user_id", "")

    if not planned:
        logger.info("execute_queries.skip", reason="no planned queries")
        return {"query_results": {}, "current_node": "execute_queries"}

    cache = get_cache_service()

    async def _run_query(q: dict) -> tuple[str, list]:
        table = q.get("table", "sessions")
        search_mode = q.get("search_mode", "faceted")
        query_text = q.get("query_text", "")
        limit = q.get("limit", 10)
        use_faceted = search_mode == "faceted"

        # Cache query results (skip user-specific/profile queries)
        is_cacheable = not user_id or search_mode != "profile"
        cache_key = make_key("query", table, query_text, search_mode, str(limit), conference_id)

        if is_cacheable:
            cached = await cache.get(cache_key)
            if cached is not None:
                return table, cached

        try:
            results = await hybrid_search(
                entity_type=table,
                query=query_text,
                conference_id=conference_id,
                use_faceted=use_faceted,
                limit=limit,
            )
            # Convert SearchResult dataclasses to dicts for serialization
            result_dicts = [asdict(r) for r in results]
            if is_cacheable and result_dicts:
                await cache.set(cache_key, result_dicts, ttl=300)
            return table, result_dicts
        except Exception as e:
            logger.warning("execute_query.failed", table=table, error=str(e))
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
    logger.info("execute_queries.done", total_results=total, tables=list(query_results.keys()))

    return {"query_results": query_results, "current_node": "execute_queries"}
