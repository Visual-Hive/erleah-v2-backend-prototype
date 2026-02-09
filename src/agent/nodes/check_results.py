"""Node 5: Validate results and identify zero-result tables."""

import structlog

from src.agent.nodes.error_wrapper import graceful_node
from src.agent.state import AssistantState
from src.config import settings

logger = structlog.get_logger()


@graceful_node("check_results", critical=False)
async def check_results(state: AssistantState) -> dict:
    """Check query results for completeness.

    Identifies tables that returned zero results.
    Determines whether a retry with relaxed filters is needed.
    Pure logic node — no I/O.
    """
    logger.info("===== NODE 6: CHECK RESULTS =====")
    query_results = state.get("query_results", {})
    retry_count = state.get("retry_count", 0)
    planned_queries = state.get("planned_queries", [])

    # Log what we have
    for table, results in query_results.items():
        logger.info("  [check_results] Table '%s': %d results", table, len(results))

    # Find tables that were queried but returned nothing
    queried_tables: set[str] = {q.get("table", "") for q in planned_queries}
    zero_result_tables: list[str] = [
        table for table in queried_tables if table and not query_results.get(table)
    ]

    # Decide if retry is needed: zero results exist AND we haven't retried yet
    needs_retry = bool(zero_result_tables) and retry_count < settings.max_retry_count

    logger.info(
        "===== NODE 6: CHECK RESULTS COMPLETE =====",
        zero_result_tables=zero_result_tables,
        needs_retry=needs_retry,
        retry_count=retry_count,
        verdict="RETRY needed"
        if needs_retry
        else "ALL GOOD — proceeding to response generation",
    )

    return {
        "zero_result_tables": zero_result_tables,
        "needs_retry": needs_retry,
        "current_node": "check_results",
    }
