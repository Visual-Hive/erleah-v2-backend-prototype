"""Node 6: Progressive filter relaxation and retry for zero-result tables.

Implements the docs' "Progressive Filter Relaxation" strategy adapted
for vector search:
  - Step 1 (retry_count=0): Relax strictness — lower score_threshold,
    double limit, search all facets (remove facet_key filter)
  - Step 2 (retry_count=1): Remove facet structure — fall back to
    master search (equivalent to removing all non-critical filters)

Critical filters (conference_id) are never removed.
"""

import asyncio
from dataclasses import asdict

import structlog

from src.agent.state import AssistantState
from src.search.faceted import hybrid_search

logger = structlog.get_logger()


def _relax_query(query: dict, retry_count: int) -> dict:
    """Relax query filters based on retry count.

    Maps the docs' "must→should" concept to vector search:
      retry 0 → lower score threshold, widen limit (relax strictness)
      retry 1 → switch to master search (remove facet structure entirely)
    """
    relaxed = {**query}

    if retry_count == 0:
        # Step 1: Relax — keep faceted but loosen matching
        relaxed["score_threshold"] = 0.15  # was 0.3
        relaxed["limit"] = query.get("limit", 10) * 2
        relaxed["search_mode"] = "faceted"  # keep faceted
        relaxed["relaxation"] = "lowered_threshold"
    else:
        # Step 2: Remove facet filters — fall back to master
        relaxed["score_threshold"] = 0.2
        relaxed["limit"] = 20
        relaxed["search_mode"] = "master"
        relaxed["relaxation"] = "master_fallback"

    return relaxed


async def relax_and_retry(state: AssistantState) -> dict:
    """Re-execute queries for tables that returned zero results.

    Uses progressive filter relaxation:
    - retry_count=0: Lower score_threshold, double limit, keep faceted
    - retry_count=1: Switch to master search (remove facet structure)
    Preserves existing results from tables that already have results.
    """
    logger.info("===== NODE 6b: RELAX AND RETRY =====")
    zero_tables = state.get("zero_result_tables", [])
    planned_queries = state.get("planned_queries", [])
    user_context = state.get("user_context", {})
    conference_id = user_context.get("conference_id", "")
    query_results = dict(state.get("query_results", {}))
    retry_count = state.get("retry_count", 0)

    logger.info(
        "  [relax_retry] Retrying tables with zero results",
        zero_tables=zero_tables,
        retry_count=retry_count,
    )

    # Find original queries for zero-result tables
    retry_queries = [q for q in planned_queries if q.get("table") in zero_tables]

    # Relax each query's filters
    relaxed_queries = [_relax_query(q, retry_count) for q in retry_queries]
    for rq in relaxed_queries:
        logger.info(
            "  [relax_retry] Relaxed query: table=%s mode=%s threshold=%s limit=%d strategy=%s",
            rq.get("table", "?"),
            rq.get("search_mode", "?"),
            rq.get("score_threshold", "?"),
            rq.get("limit", 0),
            rq.get("relaxation", "?"),
        )

    async def _retry_query(q: dict) -> tuple[str, list]:
        table = q.get("table", "sessions")
        query_text = q.get("query_text", "")
        limit = q.get("limit", 10)
        use_faceted = q.get("search_mode") == "faceted"
        score_threshold = q.get("score_threshold")

        try:
            results = await hybrid_search(
                entity_type=table,
                query=query_text,
                conference_id=conference_id,
                use_faceted=use_faceted,
                limit=limit,
                score_threshold=score_threshold,
            )
            return table, [asdict(r) for r in results]
        except Exception as e:
            logger.warning(
                "  [relax_retry] Retry query FAILED: table=%s error=%s", table, str(e)
            )
            return table, []

    tasks = [_retry_query(q) for q in relaxed_queries]
    results_list = await asyncio.gather(*tasks)

    # Merge retry results into existing results
    for table, results in results_list:
        if results:
            query_results[table] = results

    total = sum(len(v) for v in query_results.values())
    relaxation_type = (
        relaxed_queries[0].get("relaxation", "unknown") if relaxed_queries else "none"
    )

    logger.info(
        "===== NODE 6b: RELAX AND RETRY COMPLETE =====",
        total_results=total,
        retry_count=retry_count + 1,
        relaxation=relaxation_type,
        retried_tables=zero_tables,
    )

    return {
        "query_results": query_results,
        "retry_count": retry_count + 1,
        "retry_metadata": {
            "relaxation": relaxation_type,
            "tables_retried": zero_tables,
        },
        "current_node": "relax_and_retry",
    }
