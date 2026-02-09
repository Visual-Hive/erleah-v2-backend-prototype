# TASK-R4: Graph Wiring & Conditional Edges
## Wire the new reflect_and_replan node into LangGraph

**Depends on:** R1 (State & Config), R2 (Reflect & Replan Node)
**Required by:** R5 (Evaluate Feedback Loop)

---

## Overview

This is the integration task. Wire `reflect_and_replan` into the LangGraph `StateGraph`, replacing `relax_and_retry` in the retry path when `reflection_enabled=True`. The key change: the reflect node outputs new `planned_queries` and routes to `execute_queries` (not back to `check_results` directly like the old node did).

---

## 1. New Graph Flow

### Current Flow (to preserve as fallback)

```
execute_queries → check_results → [needs_retry?]
                                   ├─ yes → relax_and_retry → check_results (loop)
                                   └─ no  → generate_response
```

`relax_and_retry` executes its own searches internally and loops back to `check_results`.

### New Flow (reflection enabled)

```
execute_queries → check_results → [needs_retry?]
                                   ├─ yes → reflect_and_replan → execute_queries → check_results (loop)
                                   └─ no  → generate_response
```

Key difference: `reflect_and_replan` only **plans** (updates `planned_queries` in state). Then `execute_queries` runs those new queries. Then `check_results` evaluates again. This reuses existing nodes instead of duplicating search logic.

---

## 2. Feature-Flagged Conditional Edge

### New Conditional: `should_retry`

Replace the current `should_retry` function to route based on the feature flag:

```python
def should_retry(state: AssistantState) -> str:
    """Route based on retry need and reflection config."""
    needs_retry = state.get("needs_retry", False)
    
    if not needs_retry:
        return "generate_response"
    
    if settings.reflection_enabled:
        return "reflect_and_replan"
    else:
        return "relax_and_retry"
```

This means:
- `reflection_enabled=True` → uses the new LLM-powered path
- `reflection_enabled=False` → uses the old mechanical path (fully backward-compatible)

---

## 3. Graph Builder Changes

### File: `src/agent/graph.py`

```python
from src.agent.nodes.reflect_and_replan import reflect_and_replan

# Add the new node
graph_builder.add_node("reflect_and_replan", reflect_and_replan)

# Update conditional edges from check_results
graph_builder.add_conditional_edges(
    "check_results",
    should_retry,
    {
        "reflect_and_replan": "reflect_and_replan",  # NEW
        "relax_and_retry": "relax_and_retry",        # PRESERVED (fallback)
        "generate_response": "generate_response",
    },
)

# reflect_and_replan → execute_queries (re-run searches with new plan)
graph_builder.add_edge("reflect_and_replan", "execute_queries")

# relax_and_retry → check_results (existing, preserved)
graph_builder.add_edge("relax_and_retry", "check_results")
```

### Important: The Loop

The new flow creates a loop:

```
execute_queries → check_results → reflect_and_replan → execute_queries
```

This is safe because:
- `check_results` increments `retry_count` via `reflect_and_replan`
- `check_results` checks `retry_count < max_retry_count` before setting `needs_retry=True`
- `max_retry_count` defaults to 2, so the loop runs at most 2 times

### Visual Flow (Updated)

```
START → fetch_data
  → [profile_needs_update?] → update_profile (or skip)
  → generate_acknowledgment
  → plan_queries
  → execute_queries ←────────────────────┐
  → check_results                        │
  → [needs_retry?]                       │
     ├─ yes (reflection) → reflect_and_replan ──┘
     ├─ yes (mechanical) → relax_and_retry → check_results
     └─ no → generate_response
  → evaluate
  → END
```

---

## 4. Pipeline Node Tracking Updates

### `_PIPELINE_NODES` Set

Add the new node:

```python
_PIPELINE_NODES = {
    "fetch_data", "update_profile", "generate_acknowledgment",
    "plan_queries", "execute_queries", "check_results",
    "relax_and_retry", "reflect_and_replan",  # Both retry variants
    "generate_response", "evaluate",
}
```

### `_LLM_NODES` Set

```python
_LLM_NODES = {
    "plan_queries", "generate_response", "evaluate",
    "update_profile", "generate_acknowledgment",
    "reflect_and_replan",  # NEW: calls LLM
}
```

### `_NODE_PROMPT_KEYS` Mapping

```python
_NODE_PROMPT_KEYS: dict[str, str] = {
    # ... existing ...
    "reflect_and_replan": "reflect_and_replan",
}
```

### `PROGRESS_MESSAGES`

```python
PROGRESS_MESSAGES = {
    # ... existing ...
    "reflect_and_replan": None,  # Handled by thinking event
}
```

---

## 5. DevTools: Pipeline Store & Graph Updates

### `pipeline.js` — `PIPELINE_FLOW` and `NODE_META`

```javascript
export const PIPELINE_FLOW = [
  'fetch_data',
  'update_profile',
  'generate_acknowledgment',
  'plan_queries',
  'execute_queries',
  'check_results',
  'relax_and_retry',
  'reflect_and_replan',    // NEW
  'generate_response',
  'evaluate',
];

export const NODE_META = {
  // ... existing ...
  reflect_and_replan: { label: 'Reflect & Replan', icon: '🤔', hasLlm: true },
};
```

### `WorkflowGraph.svelte`

The existing `relax_and_retry` displays conditionally (only when its status isn't `waiting`). Apply the same pattern for `reflect_and_replan`:

```svelte
<!-- Reflection indicator (shown when active, replaces retry indicator) -->
{#if $pipeline.nodes.reflect_and_replan?.status !== 'waiting'}
  <div class="flex justify-center mt-1">
    <div class="flex items-center gap-2 px-3 py-1.5 rounded border border-purple-800/50 bg-purple-950/20">
      <span class="text-sm">🤔</span>
      <button
        class="text-xs text-purple-400 cursor-pointer hover:underline"
        onclick={() => selectNode('reflect_and_replan')}
      >
        Reflect & Replan
        {#if $pipeline.nodes.reflect_and_replan.duration_ms !== null}
          ({formatDuration($pipeline.nodes.reflect_and_replan.duration_ms)})
        {/if}
      </button>
    </div>
  </div>
{:else if $pipeline.nodes.relax_and_retry.status !== 'waiting'}
  <!-- Existing retry indicator (mechanical fallback) -->
  ...
{/if}
```

---

## 6. Preserving Original Plan

In `plan_queries` node, snapshot the first plan before any reflections can modify it:

**Option:** Do it in `check_results` or `reflect_and_replan` on first retry (already handled in R2's implementation — `original_planned_queries` is only set when empty).

This lets the DevTools and evaluate node compare "what we originally planned" vs "what we ended up searching for" — useful for understanding whether the reflection actually helped.

---

## 7. Testing Strategy

### Unit Test: Conditional Edge

```python
@pytest.mark.asyncio
async def test_should_retry_routes_to_reflection():
    """When reflection_enabled and needs_retry, route to reflect_and_replan."""
    state = {"needs_retry": True, "retry_count": 0}
    with patch("src.agent.graph.settings") as mock_settings:
        mock_settings.reflection_enabled = True
        assert should_retry(state) == "reflect_and_replan"

@pytest.mark.asyncio
async def test_should_retry_routes_to_mechanical():
    """When reflection disabled, route to relax_and_retry."""
    state = {"needs_retry": True, "retry_count": 0}
    with patch("src.agent.graph.settings") as mock_settings:
        mock_settings.reflection_enabled = False
        assert should_retry(state) == "relax_and_retry"
```

### Integration Test: Full Loop

```python
@pytest.mark.asyncio
async def test_reflection_loop_terminates():
    """Verify the reflect→execute→check loop terminates within max_retry_count."""
    # Mock the LLM to return a rewrite strategy
    # Mock execute_queries to return empty results
    # Verify loop exits after max_retry_count iterations
    # Verify thinking_updates has the expected number of records
```

---

## 8. Acceptance Criteria

- [ ] `reflect_and_replan` node registered in graph builder
- [ ] `should_retry` routes to `reflect_and_replan` when `reflection_enabled=True`
- [ ] `should_retry` routes to `relax_and_retry` when `reflection_enabled=False`
- [ ] `reflect_and_replan` → `execute_queries` edge exists
- [ ] Loop terminates within `max_retry_count` iterations
- [ ] `_PIPELINE_NODES`, `_LLM_NODES`, `_NODE_PROMPT_KEYS` include new node
- [ ] DevTools `NODE_META` and `PIPELINE_FLOW` include new node
- [ ] DevTools `WorkflowGraph.svelte` shows reflect indicator
- [ ] Existing `relax_and_retry` path still works when `reflection_enabled=False`

---

## 9. Files Modified

| File | Action |
|------|--------|
| `src/agent/graph.py` | **Modify** — add node, edges, update conditional, update tracking sets |
| `devtools/src/lib/stores/pipeline.js` | **Modify** — add to `PIPELINE_FLOW`, `NODE_META` |
| `devtools/src/components/WorkflowGraph.svelte` | **Modify** — add reflect indicator |
