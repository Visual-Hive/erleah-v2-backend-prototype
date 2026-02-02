"""Node 5: Validate results and identify zero-result tables."""

import structlog

from src.agent.state import AssistantState
from src.config import settings

logger = structlog.get_logger()


async def check_results(state: AssistantState) -> dict:
    """Check query results for completeness.

    Identifies tables that returned zero results.
    Determines whether a retry with relaxed filters is needed.
    Pure logic node — no I/O.
    """
    logger.info("check_results.start")
    query_results = state.get("query_results", {})
    retry_count = state.get("retry_count", 0)
    planned_queries = state.get("planned_queries", [])

    # Find tables that were queried but returned nothing
    queried_tables = {q.get("table") for q in planned_queries}
    zero_result_tables = [
        table for table in queried_tables if not query_results.get(table)
    ]

    # Decide if retry is needed: zero results exist AND we haven't retried yet
    needs_retry = bool(zero_result_tables) and retry_count < settings.max_retry_count

    logger.info(
        "check_results.done",
        zero_result_tables=zero_result_tables,
        needs_retry=needs_retry,
        retry_count=retry_count,
    )

    return {
        "zero_result_tables": zero_result_tables,
        "needs_retry": needs_retry,
        "current_node": "check_results",
    }
