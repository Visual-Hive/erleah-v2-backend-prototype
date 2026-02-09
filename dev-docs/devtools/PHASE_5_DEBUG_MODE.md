# Phase 5: Debug Mode Panel

> **Status**: ✅ Implemented  
> **Branch**: `feature/mini-assistant-phase-2`  
> **Depends on**: Phase 2 (TASK-01 Graceful Failure System)

## Overview

The Debug Mode panel lets you **simulate failures** in the pipeline from the DevTools GUI. Toggle a flag → send a chat message → watch the pipeline degrade gracefully with user-friendly error messages instead of crashing.

This is built on top of the `@graceful_node` decorator (TASK-01) and provides a closed-loop way to test error handling without needing to actually break external services.

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                        DevTools GUI                          │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  🐛 Debug Tab                                          │  │
│  │  ┌──────────────────────────────────────────────────┐  │  │
│  │  │ ☑ Simulate Directus failure                      │  │  │
│  │  │   💥 Forces ConnectionError in fetch_data        │  │  │
│  │  │   Affects: fetch_data, update_profile            │  │  │
│  │  ├──────────────────────────────────────────────────┤  │  │
│  │  │ ☐ Simulate no search results                     │  │  │
│  │  │   💥 Returns empty from execute_queries          │  │  │
│  │  │   Affects: execute_queries                       │  │  │
│  │  └──────────────────────────────────────────────────┘  │  │
│  └────────────────────────────────────────────────────────┘  │
│                          │                                    │
│              PUT /api/debug/simulation/{flag}                 │
│                          │                                    │
│                          ▼                                    │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  SimulationRegistry (singleton)                        │  │
│  │  { simulate_directus_failure: true, ... }              │  │
│  └──────────────────────┬─────────────────────────────────┘  │
│                          │                                    │
│              Checked at start of each node                    │
│                          │                                    │
│                          ▼                                    │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐   │
│  │  fetch_data   │  │execute_queries│  │  (future nodes)  │   │
│  │  if sim.get() │  │  if sim.get() │  │                  │   │
│  │    → raise    │  │    → return {}│  │                  │   │
│  └──────────────┘  └──────────────┘  └──────────────────┘   │
│          │                  │                                  │
│          ▼                  ▼                                  │
│  @graceful_node catches error → ErrorContext → user message   │
└──────────────────────────────────────────────────────────────┘
```

## Files

| File | Purpose |
|------|---------|
| `src/services/simulation.py` | `SimulationRegistry` singleton — stores flags in memory |
| `src/api/debug.py` | REST endpoints (`GET/PUT/POST /api/debug/simulation`) |
| `src/agent/nodes/fetch_data.py` | Checks `simulate_directus_failure` flag |
| `src/agent/nodes/execute_queries.py` | Checks `simulate_no_results` flag |
| `devtools/src/components/DebugPanel.svelte` | GUI component |
| `devtools/src/lib/stores/config.js` | `simulationFlags` / `activeSimulationCount` stores |
| `devtools/src/lib/api.js` | `fetchSimulationFlags()` / `toggleSimulationFlag()` / `resetSimulationFlags()` |
| `devtools/src/App.svelte` | Debug tab wiring (red accent when active) |

## API Reference

### `GET /api/debug/simulation`

Returns all simulation flags with their current state.

```json
{
  "simulate_directus_failure": {
    "enabled": false,
    "description": "Forces a ConnectionError in fetch_data...",
    "category": "failure",
    "affects": ["fetch_data", "update_profile"]
  },
  "simulate_no_results": {
    "enabled": false,
    "description": "Returns empty results from search queries...",
    "category": "failure",
    "affects": ["execute_queries"]
  }
}
```

### `PUT /api/debug/simulation/{flag}`

Toggle a flag on or off.

```json
// Request
{ "enabled": true }

// Response
{
  "flag": "simulate_directus_failure",
  "enabled": true,
  "description": "...",
  "category": "failure",
  "affects": ["fetch_data", "update_profile"]
}
```

### `POST /api/debug/simulation/reset`

Reset all flags to disabled. Returns the full flag state.

## How to Add a New Simulation Flag

### Step 1: Register the flag

In `src/services/simulation.py`, add to `_DEFAULT_FLAGS`:

```python
_DEFAULT_FLAGS: dict[str, SimulationFlag] = {
    # ... existing flags ...
    "simulate_slow_llm": {
        "enabled": False,
        "description": (
            "Adds a 10-second delay before LLM calls. Tests timeout handling "
            "and the user experience during slow responses."
        ),
        "category": "latency",       # "failure" | "degradation" | "latency"
        "affects": ["plan_queries", "generate_response"],
    },
}
```

### Step 2: Check the flag in the relevant node(s)

In the node file (e.g., `src/agent/nodes/plan_queries.py`):

```python
from src.services.simulation import get_simulation_registry

# At the start of the node function, before the main logic:
sim = get_simulation_registry()
if sim.get("simulate_slow_llm"):
    logger.warning("  [plan_queries] 🐛 SIMULATION: Slow LLM delay triggered")
    await asyncio.sleep(10)  # or raise TimeoutError("Simulated timeout")
```

### Step 3: (Optional) Add a label in the frontend

In `devtools/src/components/DebugPanel.svelte`, add to `FLAG_LABELS`:

```javascript
const FLAG_LABELS = {
    simulate_directus_failure: 'Simulate Directus failure',
    simulate_no_results: 'Simulate no search results',
    simulate_slow_llm: 'Simulate slow LLM (10s delay)',  // NEW
};
```

That's it! The flag will automatically appear in the Debug tab with its description, category icon, and affected node tags.

## Simulation Categories

| Category | Icon | Purpose |
|----------|------|---------|
| `failure` | 💥 | Complete service failure (ConnectionError, etc.) |
| `degradation` | ⚠️ | Partial degradation (some data missing, low quality) |
| `latency` | 🐢 | Slow responses (tests timeout handling, UX) |

## Current Flags

### `simulate_directus_failure`
- **Category**: failure
- **What it does**: Raises `ConnectionError` at the start of `fetch_data`
- **Effect**: `@graceful_node` catches it → pipeline continues without profile/history → `generate_response` gets an `error_context` and mentions the issue in its response
- **Tests**: Graceful degradation when Directus is down

### `simulate_no_results`
- **What it does**: Returns `{}` from `execute_queries` before any searches run
- **Category**: failure
- **Effect**: Pipeline enters the retry loop (relax_and_retry), eventually gives up and generates a "no results found" response
- **Tests**: Empty result handling, retry logic, user messaging

## Future Flag Ideas

Here are some simulation flags that would be useful to add:

| Flag | Category | What it simulates |
|------|----------|-------------------|
| `simulate_slow_llm` | latency | 10s delay before LLM calls (timeout handling) |
| `simulate_rate_limit` | failure | 429 from Anthropic API (rate limit messaging) |
| `simulate_partial_results` | degradation | Only return 1-2 results instead of 10 (sparse result UX) |
| `simulate_embedding_failure` | failure | OpenAI embedding service down (search completely broken) |
| `simulate_redis_failure` | degradation | Cache unavailable (everything still works, just slower) |
| `simulate_stale_profile` | degradation | Return outdated profile data (tests profile update logic) |

## Design Decisions

### Why a singleton registry (not config/env vars)?

Simulation flags need to be **toggled at runtime** from the DevTools GUI without restarting the server. Environment variables and config files require a restart. The singleton pattern is consistent with `prompt_registry` and `llm_registry`.

### Why check flags inside nodes (not in the decorator)?

The simulation logic is node-specific — a "Directus failure" should raise a `ConnectionError` (which `@graceful_node` then catches), while "no results" should return empty data (not an error). Putting the check inside the node gives full control over _how_ the failure manifests.

### Why not use middleware?

Simulation flags affect pipeline internals (specific nodes), not HTTP request handling. Middleware would be the wrong layer — we need to inject failures deep inside the LangGraph execution.

## Testing the Debug System

1. Start both servers: `make dev`
2. Open DevTools: http://localhost:5174
3. Click the **🐛 Debug** tab in the right panel
4. Toggle **Simulate Directus failure** ON
5. Send a message in the Chat panel (e.g., "Find AI sessions")
6. Watch the pipeline:
   - `fetch_data` shows an error in the Timeline
   - The response gracefully mentions database issues
   - The error is visible in the Inspector tab under node details
7. Toggle the simulation OFF and resend — normal response returns

## Relationship to TASK-01 (Graceful Failure)

The Debug Mode panel is the **testing harness** for the Graceful Failure system:

```
TASK-01 (Graceful Failure)     Debug Mode Panel
─────────────────────────     ──────────────────
@graceful_node decorator  ←── Triggers errors to test
ErrorContext propagation  ←── Creates error contexts
Error-aware prompts       ←── Exercises error messaging
Last-resort fallbacks     ←── Tests when LLM also fails
force_response edges      ←── Tests critical path
```

Without the Debug Mode panel, you'd need to manually break external services to test error handling. With it, you can test everything from the GUI in seconds.
