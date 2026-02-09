# TASK-R5: Evaluate Feedback Loop (Deferred)
## Optional regeneration when self-evaluation scores poorly

**Depends on:** R1–R4 (all prior reflection tasks)
**Status:** Deferred — design documented here for future implementation

---

## Overview

Currently the `evaluate` node runs **after** the response is already sent to the user. It scores quality (via Haiku) and stores the result, but the score is fire-and-forget — if the response is poor, nothing happens.

This task designs a feedback loop where:
1. Evaluate scores the response
2. If the score is below a threshold, the pipeline **re-generates** the response
3. The user receives an improved response (with a thinking message explaining the revision)

**Why deferred:** This is the most architecturally complex change because `evaluate` currently runs after `done` is sent. Moving it before `done` changes the user-visible latency characteristics. It also means regeneration adds another LLM call, increasing cost and time.

---

## 1. The Problem

### Current Flow

```
generate_response → [done SSE sent to user] → evaluate → END
                     ↑ response is final         ↑ score stored but unused
```

The user gets the response, then evaluation happens in the background. Even if the score is 0.3/1.0 (terrible), the user already has the bad response.

### Desired Flow

```
generate_response → evaluate → [quality OK?]
                                ├─ yes → [done SSE] → END
                                └─ no  → regenerate_response → [done SSE] → END
```

The `done` event moves to *after* evaluation, so the user only gets the final (potentially improved) response.

---

## 2. Architecture Options

### Option A: Evaluate-Before-Done (Blocking)

Move `evaluate` before the `done` event. If quality is low, regenerate.

**Pros:**
- Clean: user always gets the best response
- Simple graph change

**Cons:**
- Adds 1–2 seconds to every request (Haiku evaluation call)
- Adds 3–5 seconds when regeneration triggers (second Sonnet call)
- User waits longer before seeing the response complete

### Option B: Evaluate-After-Done with Revision (Non-Blocking)

Keep `evaluate` after `done`, but if quality is low, send a **revision event** that replaces the response.

**Pros:**
- No latency impact on the happy path (most responses are good)
- Only adds time when quality is actually poor

**Cons:**
- User sees response, then it changes — potentially confusing
- More complex SSE protocol (new `revision` event type)
- Frontend needs to handle response replacement

### Option C: Parallel Evaluate (Hybrid)

Start evaluation in parallel with the response stream. If the stream finishes and evaluation flags low quality, trigger regeneration before sending `done`.

**Pros:**
- Evaluation happens during streaming, so minimal added latency
- User only sees the final version

**Cons:**
- Complex implementation (parallel async coordination)
- Need to buffer the response to decide whether to send it or regenerate

### Recommendation: Option A for Simplicity

Start with Option A. The 1–2 second latency for Haiku is acceptable, and regeneration only triggers on genuinely poor responses (which should be rare). If latency becomes a problem, graduate to Option C.

---

## 3. Design: Option A (Evaluate-Before-Done)

### Graph Changes

```python
# Current:
graph_builder.add_edge("generate_response", "evaluate")
graph_builder.add_edge("evaluate", END)

# New:
graph_builder.add_edge("generate_response", "evaluate")
graph_builder.add_conditional_edges(
    "evaluate",
    should_regenerate,
    {
        "regenerate": "generate_response",  # Loop back
        "accept": END,
    },
)
```

### Conditional Edge: `should_regenerate`

```python
def should_regenerate(state: AssistantState) -> str:
    """Decide whether to regenerate the response based on evaluation."""
    if not settings.evaluate_feedback_enabled:
        return "accept"
    
    quality = state.get("quality_score")
    regeneration_count = state.get("regeneration_count", 0)
    
    # Only regenerate once (prevent infinite loops)
    if regeneration_count >= 1:
        return "accept"
    
    # Threshold for triggering regeneration
    if quality is not None and quality < settings.evaluate_regeneration_threshold:
        return "regenerate"
    
    return "accept"
```

### New State Fields

```python
class AssistantState(TypedDict):
    # ... existing ...
    regeneration_count: int           # How many times we've regenerated (max 1)
    evaluation_feedback: str | None   # What the evaluator said was wrong
```

### New Config

```python
class Settings(BaseSettings):
    # ... existing ...
    evaluate_feedback_enabled: bool = False     # Deferred — off by default
    evaluate_regeneration_threshold: float = 0.4  # Score below this triggers regeneration
```

---

## 4. Enhanced Evaluate Node

The current `evaluate` node only returns `quality_score` and `confidence_score`. For the feedback loop, it also needs to explain *what's wrong* so `generate_response` can do better on the second pass.

### Updated Prompt

```python
EVALUATE_SYSTEM_V2 = """\
You are a quality evaluator for an AI conference assistant called Erleah.

Given:
- The user's original question
- The search results that were available
- The assistant's response

Score the response and provide improvement guidance:

1. **quality_score** (0.0 to 1.0): How well does the response answer the question?
2. **confidence_score** (0.0 to 1.0): How confident are you in your assessment?
3. **issues** (list of strings): What's wrong with the response? (empty if quality >= 0.8)
4. **improvement_hint** (string): One sentence telling the generator how to improve.
   Only needed if quality_score < 0.4.

Return ONLY valid JSON:
{
  "quality_score": float,
  "confidence_score": float,
  "issues": ["issue1", "issue2"],
  "improvement_hint": "string or null"
}
"""
```

### Updated Return Value

```python
return {
    "quality_score": quality_score,
    "confidence_score": confidence_score,
    "evaluation": {
        "quality_score": quality_score,
        "confidence_score": confidence_score,
        "issues": scores.get("issues", []),
        "improvement_hint": scores.get("improvement_hint"),
    },
    "evaluation_feedback": scores.get("improvement_hint"),
    "current_node": "evaluate",
}
```

---

## 5. Regeneration Context

When `generate_response` runs a second time (after evaluate flags low quality), it needs to know:

1. This is a regeneration (not the first attempt)
2. What was wrong with the first response
3. The first response text (to avoid repeating the same mistakes)

### Updated `generate_response` Behavior

```python
async def generate_response(state: AssistantState) -> dict:
    regeneration_count = state.get("regeneration_count", 0)
    evaluation_feedback = state.get("evaluation_feedback")
    previous_response = state.get("response_text", "")
    
    if regeneration_count > 0 and evaluation_feedback:
        # This is a regeneration — add feedback to the prompt
        context_parts.append(
            f"\n\nIMPORTANT: Your previous response was rated low quality. "
            f"Feedback: {evaluation_feedback}\n"
            f"Previous response (DO NOT repeat this): {previous_response[:500]}\n"
            f"Please generate an improved response addressing the feedback."
        )
    
    # ... rest of generation ...
    
    return {
        "response_text": response_text,
        "referenced_ids": referenced_ids,
        "regeneration_count": regeneration_count + 1,
        "current_node": "generate_response",
    }
```

---

## 6. SSE Event Changes

### Move `done` Event

Currently `done` is sent when `generate_response` completes. With the feedback loop, it needs to move to after evaluate decides to `accept`:

```python
# Instead of sending done on generate_response on_chain_end,
# send it on evaluate on_chain_end (when should_regenerate returns "accept")
if (
    kind == "on_chain_end"
    and langgraph_node == "evaluate"
    and not done_sent
):
    done_sent = True
    yield {"event": "done", "data": {"trace_id": trace_id, "referenced_ids": referenced_ids}}
```

### New `revision` Thinking Event

If regeneration happens, send a thinking event to explain:

```python
if regeneration_count > 0:
    yield {
        "event": "thinking",
        "data": {
            "message": "I've reviewed my initial response and I can do better. Generating an improved answer...",
            "strategy": "regenerate",
            "retry_count": regeneration_count,
            "ts": time.time(),
        },
    }
```

---

## 7. Timeout Considerations

The 30-second `WORKFLOW_TIMEOUT` becomes more critical with the feedback loop:

| Path | Estimated Time |
|------|---------------|
| Normal (no retry, no regen) | ~5–8s |
| With 1 reflection retry | ~8–12s |
| With 1 reflection + 1 regeneration | ~12–18s |
| With 2 reflections + 1 regeneration | ~15–22s |
| Worst case (2 reflections + 1 regen) | ~22s (within 30s) |

The timeout is tight but workable. If evaluate + regenerate consistently pushes past 25s, consider:
- Using Haiku for evaluate (already the default — fast)
- Using a faster model for regeneration (Haiku instead of Sonnet)
- Increasing timeout to 45s when `evaluate_feedback_enabled=True`

---

## 8. Why This Is Deferred

1. **Latency risk** — adds 1–5 seconds to every request
2. **Cost** — extra LLM calls (Haiku eval + potentially Sonnet regen)
3. **Complexity** — moving `done` event timing, handling response replacement
4. **Rarity** — with good prompts and reflection (R1–R4), low-quality responses should be rare
5. **R1–R4 should be validated first** — prove that reflection improves quality before adding another layer

### When to Implement

Implement R5 when:
- R1–R4 are stable in production
- Quality scores from evaluate show a meaningful % of responses scoring < 0.4
- The DevTools Run Comparison shows that low-quality responses share common patterns
- You've tuned the prompts (via DevTools Prompt Editor) and still see quality gaps

---

## 9. Acceptance Criteria (When Implemented)

- [ ] `evaluate` runs before `done` event (when `evaluate_feedback_enabled=True`)
- [ ] `should_regenerate` conditional edge routes to `generate_response` on low scores
- [ ] `generate_response` handles regeneration context (feedback, previous response)
- [ ] `regeneration_count` limits to 1 (no infinite loops)
- [ ] Thinking event explains regeneration to the user
- [ ] Directus `thinking_output` includes regeneration records
- [ ] 30-second timeout still holds for worst-case paths
- [ ] `evaluate_feedback_enabled` defaults to `False`
- [ ] Everything works normally when the flag is off

---

## 10. Files Modified (When Implemented)

| File | Action |
|------|--------|
| `src/agent/graph.py` | **Modify** — conditional edge from evaluate, move done event |
| `src/agent/nodes/evaluate.py` | **Modify** — return improvement hints |
| `src/agent/nodes/generate_response.py` | **Modify** — handle regeneration context |
| `src/agent/state.py` | **Modify** — add `regeneration_count`, `evaluation_feedback` |
| `src/agent/prompts.py` | **Modify** — update evaluate prompt with improvement hints |
| `src/config.py` | **Modify** — add `evaluate_feedback_enabled`, `evaluate_regeneration_threshold` |
