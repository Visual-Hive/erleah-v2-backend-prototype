"""Node 6: Relax filters and re-execute queries for zero-result tables."""

import asyncio
from dataclasses import asdict

import structlog

from src.agent.state import AssistantState
from src.search.faceted import hybrid_search

logger = structlog.get_logger()


async def relax_and_retry(state: AssistantState) -> dict:
    """Re-execute queries for tables that returned zero results.

    3-step escalation based on retry_count:
    - retry_count=0: Keep faceted, double limit (broader matching)
    - retry_count=1: Switch to master search (use_faceted=False), limit=20
    Preserves existing results from tables that already have results.
    """
    logger.info("relax_and_retry.start")
    zero_tables = state.get("zero_result_tables", [])
    planned_queries = state.get("planned_queries", [])
    user_context = state.get("user_context", {})
    conference_id = user_context.get("conference_id", "")
    query_results = dict(state.get("query_results", {}))
    retry_count = state.get("retry_count", 0)

    # Find original queries for zero-result tables
    retry_queries = [q for q in planned_queries if q.get("table") in zero_tables]

    async def _retry_query(q: dict) -> tuple[str, list]:
        table = q.get("table", "sessions")
        query_text = q.get("query_text", "")
        limit = q.get("limit", 10)

        try:
            if retry_count == 0:
                # Step 1: Keep faceted, double limit
                results = await hybrid_search(
                    entity_type=table,
                    query=query_text,
                    conference_id=conference_id,
                    use_faceted=True,
                    limit=limit * 2,
                )
            else:
                # Step 2: Switch to master search, fixed limit=20
                results = await hybrid_search(
                    entity_type=table,
                    query=query_text,
                    conference_id=conference_id,
                    use_faceted=False,
                    limit=20,
                )
            return table, [asdict(r) for r in results]
        except Exception as e:
            logger.warning("retry_query.failed", table=table, error=str(e))
            return table, []

    tasks = [_retry_query(q) for q in retry_queries]
    results_list = await asyncio.gather(*tasks)

    # Merge retry results into existing results
    for table, results in results_list:
        if results:
            query_results[table] = results

    total = sum(len(v) for v in query_results.values())
    logger.info("relax_and_retry.done", total_results=total, retry_count=retry_count + 1)

    return {
        "query_results": query_results,
        "retry_count": retry_count + 1,
        "current_node": "relax_and_retry",
    }
