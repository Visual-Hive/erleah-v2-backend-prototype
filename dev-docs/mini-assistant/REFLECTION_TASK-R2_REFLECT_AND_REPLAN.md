# TASK-R2: LLM-Powered Reflect & Replan Node
## Replace mechanical retry with intelligent reflection

**Depends on:** R1 (State & Config)
**Required by:** R3, R4

---

## Overview

Create a new node `reflect_and_replan` that replaces the mechanical `relax_and_retry`. Instead of blindly lowering score thresholds, this node calls an LLM to:

1. **Diagnose** why the search returned zero results
2. **Choose a strategy** (relax, rewrite, or pivot)
3. **Generate new queries** based on its reasoning
4. **Produce a user-facing thinking message** explaining what it's doing

---

## 1. New File: `src/agent/nodes/reflect_and_replan.py`

### Node Signature

```python
async def reflect_and_replan(state: AssistantState) -> dict:
    """LLM-powered reflection on zero-result searches.
    
    Replaces the mechanical relax_and_retry when reflection_enabled=True.
    
    The LLM receives:
    - Original user message
    - Planned queries (what we searched for)
    - Results summary (what came back, what was empty)
    - Zero-result tables
    - Retry count
    
    The LLM returns:
    - reasoning: Why results were poor
    - strategy: "relax" | "rewrite" | "pivot"
    - user_message: Friendly explanation for the user
    - new_queries: Updated query plan
    
    After reasoning, the node:
    - Executes the new queries (or delegates to execute_queries via state)
    - Appends a thinking record to thinking_updates
    - Updates planned_queries with the new plan
    """
```

### Strategy Definitions

| Strategy | When LLM Should Choose It | What Happens |
|----------|---------------------------|--------------|
| `relax` | "The queries were on-target but too strict" | Lower `score_threshold` to 0.15, double `limit`, keep same `query_text` |
| `rewrite` | "The query text didn't match how the data is phrased" | LLM generates entirely new `query_text` for the zero-result tables |
| `pivot` | "We're searching the wrong tables or using the wrong search mode" | LLM changes `table`, `search_mode`, or both |

### Example Behaviors

**User:** "Find sessions about quantum computing"
**First search:** `sessions` table, `query_text: "quantum computing"` → 0 results

**LLM reflection (rewrite):**
> "The conference likely doesn't have sessions explicitly titled 'quantum computing'. The topic might be covered under 'physics', 'computing fundamentals', or 'emerging technology'. Let me search with broader terms."

**New queries:** `query_text: "physics computing emerging technology quantum"`, same table

---

**User:** "Who can help me with my ML deployment problems?"
**First search:** `sessions` table → 0 results

**LLM reflection (pivot):**
> "The user is looking for help with ML deployment — this sounds more like an exhibitor offering services than a session topic. Let me search the exhibitors table instead."

**New queries:** `table: "exhibitors"`, `query_text: "ML deployment MLOps services"`

---

## 2. New Prompt: `REFLECT_AND_REPLAN_SYSTEM`

### File: `src/agent/prompts.py`

```python
REFLECT_AND_REPLAN_SYSTEM = """\
You are reflecting on search results for a conference assistant called Erleah.

The user asked a question, and one or more of our database searches returned zero results. \
Your job is to figure out WHY and decide what to try next.

You will receive:
- The user's original message
- The queries we planned and executed
- Which tables returned results and which returned nothing
- The retry count (how many times we've already retried)

Analyze the situation and choose ONE strategy:

1. **"relax"** — The queries were on-target but too strict. Lower the score \
threshold and widen the result limit. Use this when the query text is good but \
the vector similarity threshold was too high.

2. **"rewrite"** — The query text didn't match how the data is phrased. Generate \
entirely new query text that approaches the topic from a different angle. Use this \
when the user used jargon, abbreviations, or phrasing that the conference data \
probably doesn't use.

3. **"pivot"** — We're searching the wrong tables or using the wrong search mode. \
Switch from sessions to exhibitors (or vice versa), or switch between faceted and \
master search. Use this when the user's need maps to a different entity type than \
we originally searched.

Also write a brief, friendly message (1-2 sentences) to show the user, explaining \
what you're doing. Do NOT mention technical details like "score thresholds" or \
"faceted search" — speak naturally as if you're a helpful assistant.

Return ONLY valid JSON:
{
  "reasoning": "Your internal analysis of why results were poor (developer-facing)",
  "strategy": "relax" | "rewrite" | "pivot",
  "user_message": "Friendly message for the user (1-2 sentences)",
  "new_queries": [
    {"table": "sessions|exhibitors|speakers", "search_mode": "faceted|master", "query_text": "...", "limit": 10}
  ]
}
"""
```

### Register in Prompt Registry

**File: `src/agent/prompt_registry.py`**

Add to `_PROMPT_DEFAULTS`:

```python
_PROMPT_DEFAULTS: dict[str, tuple[str, str]] = {
    # ... existing ...
    "reflect_and_replan": (REFLECT_AND_REPLAN_SYSTEM, "reflect_and_replan"),
}
```

This makes the reflection prompt editable via the DevTools Prompt Editor — crucial for tuning.

---

## 3. Node Implementation Skeleton

```python
"""Node: LLM-powered reflection and query re-planning."""

import json
import time

import structlog
from langchain_core.messages import HumanMessage, SystemMessage

from src.agent.llm_registry import get_llm_registry
from src.agent.prompt_registry import get_prompt_registry
from src.agent.state import AssistantState
from src.config import settings

logger = structlog.get_logger()


async def reflect_and_replan(state: AssistantState) -> dict:
    """Reflect on zero-result searches and produce a new query plan."""
    logger.info("===== NODE 6b: REFLECT AND REPLAN =====")
    
    zero_tables = state.get("zero_result_tables", [])
    planned_queries = state.get("planned_queries", [])
    query_results = dict(state.get("query_results", {}))
    retry_count = state.get("retry_count", 0)
    messages = state["messages"]
    user_message = messages[-1].content if messages else ""
    thinking_updates = list(state.get("thinking_updates", []))
    
    # Preserve original plan on first reflection
    original = state.get("original_planned_queries", [])
    if not original:
        original = list(planned_queries)
    
    # Build context for the LLM
    results_summary = {}
    for table, results in query_results.items():
        results_summary[table] = f"{len(results)} results"
    for table in zero_tables:
        results_summary[table] = "0 results"
    
    reflection_prompt = json.dumps({
        "user_message": str(user_message),
        "planned_queries": planned_queries,
        "results_summary": results_summary,
        "zero_result_tables": zero_tables,
        "retry_count": retry_count,
    }, indent=2)
    
    try:
        registry = get_prompt_registry()
        llm = get_llm_registry().get_model("reflect_and_replan")
        result = await llm.ainvoke([
            SystemMessage(
                content=registry.get("reflect_and_replan"),
                additional_kwargs={"cache_control": {"type": "ephemeral"}},
            ),
            HumanMessage(content=reflection_prompt),
        ])
        
        content = str(result.content).strip()
        if content.startswith("```"):
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        
        reflection = json.loads(content)
        
        reasoning = reflection.get("reasoning", "")
        strategy = reflection.get("strategy", "relax")
        user_msg = reflection.get("user_message", "Let me try a different approach...")
        new_queries = reflection.get("new_queries", planned_queries)
        
        logger.info(
            "  [reflect] LLM reflection complete",
            strategy=strategy,
            reasoning=reasoning[:200],
            user_message=user_msg,
            new_query_count=len(new_queries),
        )
        
    except Exception as e:
        # Fallback to mechanical relaxation if LLM fails
        logger.warning("  [reflect] LLM reflection FAILED, falling back to mechanical relax", error=str(e))
        reasoning = f"LLM reflection failed: {e}"
        strategy = "relax"
        user_msg = "Let me broaden my search..."
        new_queries = _mechanical_relax(planned_queries, zero_tables, retry_count)
    
    # Apply strategy-specific adjustments to new_queries
    if strategy == "relax":
        new_queries = _apply_relax(new_queries, retry_count)
    
    # Build thinking record
    thinking_record = {
        "message": user_msg,
        "strategy": strategy,
        "retry_count": retry_count + 1,
        "ts": time.time(),
    }
    thinking_updates.append(thinking_record)
    
    # Execute the new queries (reuse execute_queries logic)
    # The new planned_queries will flow into execute_queries on the next loop
    
    logger.info(
        "===== NODE 6b: REFLECT AND REPLAN COMPLETE =====",
        strategy=strategy,
        retry_count=retry_count + 1,
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


def _mechanical_relax(queries, zero_tables, retry_count):
    """Fallback: same logic as current relax_and_retry."""
    relaxed = []
    for q in queries:
        if q.get("table") in zero_tables:
            r = {**q}
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


def _apply_relax(queries, retry_count):
    """When LLM chose 'relax', apply threshold/limit adjustments."""
    for q in queries:
        if retry_count == 0:
            q.setdefault("score_threshold", 0.15)
            q["limit"] = max(q.get("limit", 10), 20)
        else:
            q["score_threshold"] = 0.2
            q["limit"] = 20
    return queries
```

---

## 4. Important: Graph Flow Change

Note that `reflect_and_replan` updates `planned_queries` in state. The graph must then route to `execute_queries` (not directly re-search like the current `relax_and_retry` does). This is covered in TASK-R4.

The current `relax_and_retry` executes searches internally. The new `reflect_and_replan` only **plans** — it outputs new queries and lets the existing `execute_queries` node do the searching. This is cleaner separation of concerns.

---

## 5. LLM Model Assignment

Register in `src/agent/llm_registry.py` so it appears in the DevTools Model Selector:

```python
# In _DEFAULT_ASSIGNMENTS or equivalent
"reflect_and_replan": ModelConfig(
    provider="anthropic",
    model_id="claude-sonnet-4-20250514",  # Same as plan_queries
    ...
)
```

Using Sonnet for reflection keeps quality high. Could be swapped to Haiku for speed via DevTools.

---

## 6. Acceptance Criteria

- [ ] `src/agent/nodes/reflect_and_replan.py` exists with the node function
- [ ] `REFLECT_AND_REPLAN_SYSTEM` prompt added to `prompts.py`
- [ ] Prompt registered in `prompt_registry.py` (editable via DevTools)
- [ ] Model registered in `llm_registry.py` (swappable via DevTools)
- [ ] Node returns updated `planned_queries`, `thinking_updates`, `reflection_*` fields
- [ ] Falls back to mechanical relax if LLM call fails
- [ ] `relax_and_retry.py` kept intact as fallback (not deleted)

---

## 7. Files Created/Modified

| File | Action |
|------|--------|
| `src/agent/nodes/reflect_and_replan.py` | **Create** — new node |
| `src/agent/prompts.py` | **Modify** — add `REFLECT_AND_REPLAN_SYSTEM` |
| `src/agent/prompt_registry.py` | **Modify** — register new prompt |
| `src/agent/llm_registry.py` | **Modify** — register model for node |
