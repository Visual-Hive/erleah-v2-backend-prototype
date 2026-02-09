# Reflection & Thinking Architecture — Task Index
## Making the Agent Genuinely Reflective

**Goal:** Transform the agent from a mechanical retry loop into a genuinely reflective system that reasons about poor results, re-plans its approach, and narrates its thinking to users in real time.

**Context:** The current pipeline has a `check_results → relax_and_retry → check_results` loop that mechanically lowers score thresholds when searches return zero results. This works but doesn't reason about *why* results were poor or consider fundamentally different strategies. Users see static progress messages like "Expanding search..." instead of the agent's actual reasoning.

---

## Current State vs Target State

| Capability | Current | Target |
|---|---|---|
| Retry on zero results | ✅ Mechanical (threshold relaxation) | ✅ LLM-powered (reason + re-plan) |
| Retry strategy | Lower threshold → master fallback | Relax / Rewrite queries / Pivot tables |
| User progress | Static strings ("Expanding search...") | Agent's actual reasoning narrated |
| Thinking in production UI | ❌ Not visible | ✅ Via `thinking_output` field on Directus message |
| Thinking in DevTools | ❌ Buried in node output JSON | ✅ Dedicated `thinking` SSE event |
| Self-evaluation feedback | ❌ Score-and-forget | ✅ Optional regeneration on low quality |
| Backward-compatible | N/A | ✅ Feature-flagged, old behavior preserved |

---

## Task Breakdown

| Task | Title | Scope | Depends On |
|------|-------|-------|------------|
| [TASK-R1](./REFLECTION_TASK-R1_STATE_AND_CONFIG.md) | State & Config Foundations | New state fields, config flags, Directus schema | — |
| [TASK-R2](./REFLECTION_TASK-R2_REFLECT_AND_REPLAN.md) | LLM-Powered Reflect & Replan Node | New node replacing mechanical retry | R1 |
| [TASK-R3](./REFLECTION_TASK-R3_THINKING_EVENTS.md) | Thinking Events (SSE + Directus) | Stream reasoning to users and DevTools | R1, R2 |
| [TASK-R4](./REFLECTION_TASK-R4_GRAPH_WIRING.md) | Graph Wiring & Conditional Edges | Wire new node into LangGraph, feature flag | R1, R2 |
| [TASK-R5](./REFLECTION_TASK-R5_EVALUATE_FEEDBACK.md) | Evaluate Feedback Loop (Deferred) | Optional regeneration on low quality scores | R1–R4 |

---

## Implementation Order

```
R1 (foundations) → R2 (new node) → R3 (thinking events) → R4 (wire it up)
                                                              ↓
                                                        R5 (evaluate loop — deferred)
```

**Estimated effort:** R1–R4 can be done in a single session. R5 is a separate, more ambitious piece.

---

## Architecture Overview

### New Pipeline Flow

```
plan_queries → execute_queries → check_results
                                      │
                              [needs_retry?]
                              │ yes          │ no
                    reflect_and_replan    generate_response
                              │
                       execute_queries → check_results (loop, max 2)
```

### Key Difference from Current

**Current:** `check_results` → pure logic → `relax_and_retry` (mechanically lower thresholds) → re-execute

**New:** `check_results` → pure logic → `reflect_and_replan` (LLM reasons about failure, chooses strategy, rewrites queries) → re-execute

The LLM in `reflect_and_replan` can choose from three strategies:
- **relax** — lower thresholds (same as today)
- **rewrite** — generate entirely new query text
- **pivot** — switch tables or search modes

### Thinking Visibility

```
Backend                          Frontend (Production Widget)
───────                          ────────────────────────────
reflect_and_replan               Directus message.thinking_output
  ├─ LLM reasons about failure   updated via PATCH with JSON array
  ├─ Chooses strategy             of thinking records
  └─ Emits thinking SSE event  → Frontend listens via WebSocket
                                  and renders thinking steps
                                  between acknowledgment and response

Also: DevTools receives          DevTools
  thinking SSE event directly  → Shown in ChatInput + NodeDetail
```
