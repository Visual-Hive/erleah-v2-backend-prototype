# TASK-R1: State & Config Foundations
## New state fields, config flags, and Directus schema changes

**Depends on:** Nothing (this is the foundation)
**Required by:** R2, R3, R4, R5

---

## Overview

Before building the reflection node or thinking events, we need the data structures to carry reflection state through the pipeline, the config flags to feature-toggle the new behavior, and the Directus schema change to persist thinking output for the production frontend.

---

## 1. New State Fields

### File: `src/agent/state.py`

Add these fields to `AssistantState`:

```python
class AssistantState(TypedDict):
    # ... existing fields ...

    # --- reflect_and_replan (NEW) ---
    reflection_reasoning: str              # LLM's reasoning about why results were poor
    reflection_strategy: str               # "relax" | "rewrite" | "pivot" | ""
    thinking_updates: list[dict]           # Thinking records: [{message, strategy, ts}]
    original_planned_queries: list[dict]   # Preserve first plan for comparison
```

### Field Details

| Field | Type | Default | Purpose |
|-------|------|---------|---------|
| `reflection_reasoning` | `str` | `""` | The LLM's free-text explanation of what went wrong and what it's trying next |
| `reflection_strategy` | `str` | `""` | One of `"relax"`, `"rewrite"`, `"pivot"`, or empty if no reflection happened |
| `thinking_updates` | `list[dict]` | `[]` | Accumulated thinking records, each with `{message, strategy, retry_count, ts}` |
| `original_planned_queries` | `list[dict]` | `[]` | Snapshot of the first `planned_queries` before any reflection rewrites them |

### Initialization in `graph.py`

Update `initial_state` in `stream_agent_response()`:

```python
initial_state: AssistantState = {
    # ... existing fields ...
    "reflection_reasoning": "",
    "reflection_strategy": "",
    "thinking_updates": [],
    "original_planned_queries": [],
}
```

---

## 2. Config Flags

### File: `src/config.py`

Add to `Settings`:

```python
class Settings(BaseSettings):
    # ... existing fields ...

    # Reflection (LLM-powered retry)
    reflection_enabled: bool = True         # Use LLM reflection vs mechanical retry
    reflection_model_node: str = "reflect"  # LLM registry key for the reflection model
```

### Behavior

| `reflection_enabled` | Pipeline behavior |
|---|---|
| `True` (default) | `check_results` → `reflect_and_replan` (LLM reasons + rewrites queries) |
| `False` | `check_results` → `relax_and_retry` (current mechanical behavior, preserved) |

This makes the feature fully backward-compatible and A/B testable via the DevTools model selector.

---

## 3. Directus Schema Change

### New field on `messages` collection: `thinking_output`

| Field | Type | Interface | Default |
|-------|------|-----------|---------|
| `thinking_output` | `json` | Code (JSON) | `null` |

### Schema

```json
{
  "field": "thinking_output",
  "type": "json",
  "meta": {
    "interface": "input-code",
    "options": {
      "language": "json"
    },
    "note": "Agent thinking steps shown to user during processing. Array of thinking records.",
    "hidden": false,
    "readonly": false
  }
}
```

### Data Format

When the agent reflects, `thinking_output` is updated with an array of records:

```json
[
  {
    "message": "I searched for 'quantum computing sessions' but found no results. Let me try a broader search for 'physics and computing' sessions instead.",
    "strategy": "rewrite",
    "retry_count": 1,
    "ts": 1738000000.123
  },
  {
    "message": "Still no exact matches. Expanding to search across all session topics with lower thresholds.",
    "strategy": "relax",
    "retry_count": 2,
    "ts": 1738000002.456
  }
]
```

### How It's Updated

The backend PATCHes `thinking_output` on the assistant message each time `reflect_and_replan` runs:

```python
await directus.update_message_thinking(
    message_id=message_id,
    thinking_output=state["thinking_updates"],
)
```

The frontend's existing WebSocket subscription to the message will pick up updates automatically — no new subscription needed.

### Directus Client Addition

Add to `src/services/directus.py`:

```python
async def update_message_thinking(
    self,
    message_id: str,
    thinking_output: list[dict],
) -> None:
    """Update the thinking_output field on a message."""
    await self._patch(
        f"/items/messages/{message_id}",
        json={"thinking_output": thinking_output},
    )
```

---

## 4. Acceptance Criteria

- [ ] `AssistantState` has all four new fields
- [ ] `initial_state` in `graph.py` initializes them correctly
- [ ] `Settings` has `reflection_enabled` flag (default `True`)
- [ ] Directus `messages` collection has `thinking_output` JSON field
- [ ] `DirectusClient` has `update_message_thinking()` method
- [ ] Existing tests still pass (no breaking changes)

---

## 5. Files Modified

| File | Change |
|------|--------|
| `src/agent/state.py` | Add 4 new fields to `AssistantState` |
| `src/agent/graph.py` | Initialize new fields in `initial_state` |
| `src/config.py` | Add `reflection_enabled` setting |
| `src/services/directus.py` | Add `update_message_thinking()` method |
| Directus admin UI | Add `thinking_output` field to `messages` collection |
