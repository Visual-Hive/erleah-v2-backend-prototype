"""Node 6b: LLM-powered reflection and query re-planning.

Replaces the mechanical relax_and_retry when reflection_enabled=True.

The LLM receives:
- Original user message
- Planned queries (what we searched for)
- Results summary (what came back, what was empty)
- Zero-result tables
- Retry count

The LLM returns:
- reasoning: Why results were poor (developer-facing)
- strategy: "relax" | "rewrite" | "pivot"
- user_message: Friendly explanation for the user
- new_queries: Updated query plan

After reasoning, the node:
- Updates planned_queries with the new plan (execute_queries re-runs them)
- Appends a thinking record to thinking_updates
- Does NOT execute searches itself (clean separation of concerns)
"""

import json
import time

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.llm_registry import get_llm_registry
from src.agent.nodes.error_wrapper import graceful_node
from src.agent.prompt_registry import get_prompt_registry
from src.agent.state import AssistantState

logger = structlog.get_logger()


@graceful_node("reflect_and_replan", critical=False)
async def reflect_and_replan(state: AssistantState) -> dict:
    """Reflect on zero-result searches and produce a new query plan.

    Chooses one of three strategies:
    - relax: lower score threshold, widen limit
    - rewrite: generate new query text that better matches the data
    - pivot: switch table or search mode entirely

    Falls back to mechanical relax if the LLM call fails.
    """
    logger.info("===== NODE 6b: REFLECT AND REPLAN =====")

    zero_tables = state.get("zero_result_tables", [])
    planned_queries = state.get("planned_queries", [])
    query_results = dict(state.get("query_results", {}))
    retry_count = state.get("retry_count", 0)
    messages = state["messages"]
    user_message = messages[-1].content if messages else ""
    thinking_updates = list(state.get("thinking_updates", []))

    # Preserve the original plan on first reflection (never overwrite)
    original = state.get("original_planned_queries", [])
    if not original:
        original = list(planned_queries)

    # Build results summary for the LLM
    results_summary: dict[str, str] = {}
    for table, results in query_results.items():
        results_summary[table] = f"{len(results)} results"
    for table in zero_tables:
        results_summary[table] = "0 results"

    reflection_input = json.dumps(
        {
            "user_message": str(user_message),
            "planned_queries": planned_queries,
            "results_summary": results_summary,
            "zero_result_tables": zero_tables,
            "retry_count": retry_count,
        },
        indent=2,
    )

    reasoning = ""
    strategy = "relax"
    user_msg = "Let me try a different approach..."
    new_queries: list[dict] = list(planned_queries)

    try:
        registry = get_prompt_registry()
        llm = get_llm_registry().get_model("reflect_and_replan")

        result = await llm.ainvoke(
            [
                SystemMessage(
                    content=registry.get("reflect_and_replan"),
                    additional_kwargs={"cache_control": {"type": "ephemeral"}},
                ),
                HumanMessage(content=reflection_input),
            ]
        )

        content = str(result.content).strip()
        # Strip markdown code fences if present
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()

        reflection = json.loads(content)

        reasoning = reflection.get("reasoning", "")
        strategy = reflection.get("strategy", "relax")
        user_msg = reflection.get(
            "user_message", "Let me try a different approach..."
        )
        new_queries = reflection.get("new_queries", list(planned_queries))

        logger.info(
            "  [reflect] LLM reflection complete",
            strategy=strategy,
            reasoning=reasoning[:200],
            user_message=user_msg[:100],
            new_query_count=len(new_queries),
        )

    except Exception as e:
        # Fallback to mechanical relaxation — never let the agent get stuck
        logger.warning(
            "  [reflect] LLM call FAILED — falling back to mechanical relax",
            error=str(e),
        )
        reasoning = f"LLM reflection failed: {e}"
        strategy = "relax"
        user_msg = "Let me broaden my search..."
        new_queries = _mechanical_relax(planned_queries, zero_tables, retry_count)

    # Apply numeric threshold/limit adjustments when strategy is "relax"
    if strategy == "relax":
        new_queries = _apply_relax(new_queries, retry_count)

    # Build thinking record for SSE + Directus
    thinking_record: dict = {
        "message": user_msg,
        "strategy": strategy,
        "retry_count": retry_count + 1,
        "ts": time.time(),
    }
    thinking_updates.append(thinking_record)

    logger.info(
        "===== NODE 6b: REFLECT AND REPLAN COMPLETE =====",
        strategy=strategy,
        new_retry_count=retry_count + 1,
        thinking_updates_count=len(thinking_updates),
    )

    return {
        "planned_queries": new_queries,
        "retry_count": retry_count + 1,
        "reflection_reasoning": reasoning,
        "reflection_strategy": strategy,
        "thinking_updates": thinking_updates,
        "original_planned_queries": original,
        "current_node": "reflect_and_replan",
    }


def _mechanical_relax(
    queries: list[dict], zero_tables: list[str], retry_count: int
) -> list[dict]:
    """Fallback: same logic as the current relax_and_retry node."""
    relaxed = []
    for q in queries:
        if q.get("table") in zero_tables:
            r = dict(q)
            if retry_count == 0:
                r["score_threshold"] = 0.15
                r["limit"] = q.get("limit", 10) * 2
            else:
                r["search_mode"] = "master"
                r["score_threshold"] = 0.2
                r["limit"] = 20
            relaxed.append(r)
        else:
            relaxed.append(q)
    return relaxed


def _apply_relax(queries: list[dict], retry_count: int) -> list[dict]:
    """When LLM chose 'relax', apply threshold/limit adjustments."""
    adjusted = []
    for q in queries:
        q = dict(q)
        if retry_count == 0:
            q.setdefault("score_threshold", 0.15)
            q["limit"] = max(q.get("limit", 10), 20)
        else:
            q["score_threshold"] = 0.2
            q["limit"] = 20
        adjusted.append(q)
    return adjusted
