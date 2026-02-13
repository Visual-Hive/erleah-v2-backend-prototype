"""Node 4: Parallel query execution via hybrid_search."""

import asyncio
from dataclasses import asdict

import structlog

from src.agent.nodes.error_wrapper import graceful_node
from src.agent.state import AssistantState
from src.search.faceted import hybrid_search, extract_display_name
from src.services.cache import get_cache_service, make_key
from src.services.simulation import get_simulation_registry

logger = structlog.get_logger()


@graceful_node("execute_queries", critical=False)
async def execute_queries(state: AssistantState) -> dict:
    """Execute all planned queries in parallel using hybrid_search."""
    logger.info("===== NODE 5: EXECUTE QUERIES =====")
    planned = state.get("planned_queries", [])
    user_context = state.get("user_context", {})
    # Use None as default for single-tenant deployments (no conference_id filter)
    conference_id = user_context.get("conference_id") or None
    
    logger.info(
        "  [execute_queries] User context: conference_id=%s",
        conference_id or "ALL (no filter)",
    )

    # Check simulation flags
    sim = get_simulation_registry()
    if sim.get("simulate_no_results"):
        logger.warning(
            "  [execute_queries] 🐛 SIMULATION: Returning empty results for all %d queries",
            len(planned),
        )
        return {"query_results": {}, "current_node": "execute_queries"}

    if not planned:
        logger.info("  [execute_queries] SKIPPED — no planned queries")
        return {"query_results": {}, "current_node": "execute_queries"}

    unique_texts = list(
        set(q.get("query_text", "") for q in planned if q.get("query_text"))
    )

    query_mode = state.get("query_mode", "hybrid")

    # ---------------------------------------------------------
    # BUSINESS LOGIC: Define distinct thresholds for distinct tools
    # ---------------------------------------------------------
    if query_mode == "specific":
        # Master Search (Cosine Similarity): 0.15 is sensitive enough for name lookups
        threshold = 0.15
    else:
        # Faceted Search (Composite Score 0-10): 3.0 requires meaningful matches
        threshold = 3.0

    logger.info(
        "  [execute_queries] Intent-based threshold active",
        query_mode=query_mode,
        threshold=threshold,
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

        # Architecture choice: If specific, force Master Search.
        # Faceted search is for recommendations, not lookups.
        use_faceted = (search_mode == "faceted") and (query_mode != "specific")

        vector = text_to_vector.get(query_text)

        try:
            logger.info(
                "  [execute_queries] Searching Qdrant: table=%s faceted=%s mode=%s query='%s'",
                table,
                use_faceted,
                query_mode,
                query_text[:80],
            )
            results = await hybrid_search(
                entity_type=table,
                query=query_text,
                conference_id=conference_id,
                use_faceted=use_faceted,
                limit=limit,
                query_vector=vector,
                score_threshold=None,  # We filter composite/raw manually below for precision
            )

            # ---------------------------------------------------------
            # MANUAL FILTERING: Apply the correct scale for the tool used
            # ---------------------------------------------------------
            filtered_results = []
            for r in results:
                # If we used Master search, total_score is 0.0-1.0
                # If we used Faceted search, total_score is 0.0-10.0
                if r.total_score >= threshold:
                    filtered_results.append(asdict(r))

            logger.info(
                "  [execute_queries] Results for %s: %d matches found (after threshold %.2f)",
                table,
                len(filtered_results),
                threshold,
            )
            return table, filtered_results
        except Exception as e:
            logger.warning(
                "  [execute_queries] Query FAILED: table=%s error=%s", table, str(e)
            )
            return table, []

    tasks = [_run_query(q) for q in planned]
    results_list = await asyncio.gather(*tasks)

    query_results: dict[str, list] = {}
    for table, results in results_list:
        if table in query_results:
            query_results[table].extend(results)
        else:
            query_results[table] = results

    return {"query_results": query_results, "current_node": "execute_queries"}