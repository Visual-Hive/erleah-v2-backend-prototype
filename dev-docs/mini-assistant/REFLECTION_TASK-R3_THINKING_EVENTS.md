# TASK-R3: Thinking Events (SSE + Directus)
## Stream the agent's reasoning to users and DevTools

**Depends on:** R1 (State & Config), R2 (Reflect & Replan Node)
**Required by:** R4 (Graph Wiring)

---

## Overview

When the agent reflects and re-plans, its reasoning should be visible to:

1. **Production widget users** — via `thinking_output` field on the Directus message (WebSocket subscription)
2. **DevTools users** — via a `thinking` SSE event (real-time in the debug stream)

This task covers both delivery mechanisms.

---

## 1. SSE `thinking` Event

### Emitted from: `stream_agent_response()` in `src/agent/graph.py`

When the `reflect_and_replan` node completes (detected via `on_chain_end`), emit a `thinking` SSE event with the latest thinking record.

### Event Format

```python
yield {
    "event": "thinking",
    "data": {
        "message": "I didn't find any sessions about quantum computing. Let me search for related topics like physics and emerging technology instead.",
        "strategy": "rewrite",
        "retry_count": 1,
        "ts": 1738000000.123,
    },
}
```

### Where to Add It

In `stream_agent_response()`, after the existing `on_chain_end` handling for acknowledgments, add:

```python
# Send thinking event when reflect_and_replan finishes
if (
    kind == "on_chain_end"
    and langgraph_node == "reflect_and_replan"
):
    output = event.get("data", {}).get("output", {})
    if isinstance(output, dict):
        thinking_updates = output.get("thinking_updates", [])
        if thinking_updates:
            # Send the latest thinking record
            latest = thinking_updates[-1]
            logger.info(
                "  [sse] thinking event",
                strategy=latest.get("strategy"),
                message=latest.get("message", "")[:100],
            )
            yield {
                "event": "thinking",
                "data": latest,
            }
```

### Progress Message Update

Also update `PROGRESS_MESSAGES` to use the dynamic thinking message instead of a static string:

```python
PROGRESS_MESSAGES = {
    # ... existing ...
    "reflect_and_replan": None,  # Handled by thinking event, not static progress
}
```

---

## 2. Directus `thinking_output` Updates

### When to Write

Each time `reflect_and_replan` completes, PATCH the assistant message's `thinking_output` field with the full `thinking_updates` array.

### Where to Add It

This can be done in one of two places:

**Option A: Inside the `reflect_and_replan` node itself** (simpler, but the node needs access to `message_id`)

```python
# At the end of reflect_and_replan():
user_context = state.get("user_context", {})
message_id = user_context.get("message_id")
if message_id:
    directus = get_directus_client()
    await directus.update_message_thinking(
        message_id=message_id,
        thinking_output=thinking_updates,
    )
```

**Option B: In `stream_agent_response()` alongside the SSE event** (keeps the node pure, Directus write is in the streaming layer)

```python
# After emitting the thinking SSE event:
if message_id and thinking_updates:
    try:
        directus = get_directus_client()
        await directus.update_message_thinking(
            message_id=message_id,
            thinking_output=thinking_updates,
        )
    except Exception as e:
        logger.warning("  [sse] Failed to update thinking_output in Directus", error=str(e))
```

**Recommendation:** Option A is cleaner — the node owns its data writes. But note that the current pipeline doesn't pass `message_id` through state. If it's available via `user_context`, use Option A. Otherwise, Option B works from the streaming layer where `trace_id` and context are available.

### Important: `message_id` Availability

Check if `user_context` carries `message_id`. Looking at the current `initial_state`:

```python
"user_context": user_context,  # Contains user_id, conference_id, conversation_id
```

If `message_id` isn't in `user_context` today, it needs to be added when the frontend sends it. For the DevTools flow (which uses SSE directly, not Directus messages), this field may be empty — and that's fine, the Directus write simply skips.

For production: the frontend creates the assistant message in Directus *before* calling the backend, and passes `message_id` in the request. The backend should thread this through `user_context`.

---

## 3. Frontend Consumption

### Production Widget (Directus WebSocket)

The frontend already subscribes to message updates via WebSocket. When `thinking_output` changes on the message, it arrives as a field update:

```javascript
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  if (data.type === 'subscription' && data.event === 'update') {
    const message = data.data[0];
    
    // Existing: render streaming response text
    if (message.messageText) {
      displayResponse(message.messageText);
    }
    
    // NEW: render thinking steps
    if (message.thinking_output && message.thinking_output.length > 0) {
      displayThinkingSteps(message.thinking_output);
    }
  }
};
```

### Suggested UI Treatment

Thinking steps should appear **between** the acknowledgment and the response, styled distinctly:

```
┌─────────────────────────────────────────┐
│ 💬 "Sure, let me find quantum          │  ← Acknowledgment
│     computing sessions for you!"        │
├─────────────────────────────────────────┤
│ 🔄 "I didn't find any sessions about   │  ← Thinking step 1
│     quantum computing specifically.     │
│     Let me search for related topics    │
│     like physics and emerging tech."    │
├─────────────────────────────────────────┤
│ 🔄 "Broadening my search a bit more    │  ← Thinking step 2 (if needed)
│     to find the best matches..."        │
├─────────────────────────────────────────┤
│ 📝 "Here's what I found:               │  ← Final response (streamed)
│     1. Advanced Physics in Computing    │
│     2. Emerging Tech Frontiers          │
│     ..."                                │
└─────────────────────────────────────────┘
```

Thinking steps should:
- Use a muted/italic style (not as prominent as the final response)
- Show a subtle animation/spinner while the retry is in progress
- Disappear or collapse once the final response arrives (optional — could keep for transparency)

---

## 4. DevTools Consumption

### Store Update: `src/lib/stores/pipeline.js`

Add a `thinkingUpdates` array to the pipeline state:

```javascript
function createInitialState() {
  return {
    // ... existing ...
    thinkingUpdates: [],  // Array of thinking records
  };
}
```

Add a handler:

```javascript
export function handleThinking(data) {
  pipeline.update(state => ({
    ...state,
    thinkingUpdates: [...state.thinkingUpdates, data],
    eventsReceived: state.eventsReceived + 1,
  }));
}
```

### API Dispatch: `src/lib/api.js`

Add to `parseAndDispatchSSE()`:

```javascript
case 'thinking':
  handleThinking(data);
  break;
```

### ChatInput Display

Show thinking steps in `ChatInput.svelte` between acknowledgment and response:

```svelte
{#each $pipeline.thinkingUpdates as step}
  <div class="p-2 rounded bg-yellow-950/20 border border-yellow-900/30">
    <div class="text-[10px] text-yellow-400 uppercase mb-1">
      Thinking (retry {step.retry_count}) — {step.strategy}
    </div>
    <div class="text-xs text-yellow-200 italic">{step.message}</div>
  </div>
{/each}
```

### NodeDetail Display

When inspecting `reflect_and_replan` in the Inspector, show:
- Reasoning (developer-facing, from `output.reflection_reasoning`)
- Strategy chosen
- Original queries vs new queries
- Thinking message sent to user

---

## 5. Acceptance Criteria

- [ ] `thinking` SSE event emitted when `reflect_and_replan` finishes
- [ ] `thinking_output` field on Directus message updated with accumulated records
- [ ] DevTools pipeline store handles `thinking` events
- [ ] DevTools ChatInput renders thinking steps between acknowledgment and response
- [ ] DevTools NodeDetail shows reflection details when inspecting the reflect node
- [ ] Production widget can render thinking steps via WebSocket message updates
- [ ] Thinking events include: `message`, `strategy`, `retry_count`, `ts`

---

## 6. Files Modified

| File | Action |
|------|--------|
| `src/agent/graph.py` | **Modify** — emit `thinking` SSE event, update Directus |
| `src/services/directus.py` | **Modify** — add `update_message_thinking()` (if not done in R1) |
| `devtools/src/lib/stores/pipeline.js` | **Modify** — add `thinkingUpdates`, `handleThinking` |
| `devtools/src/lib/api.js` | **Modify** — dispatch `thinking` event |
| `devtools/src/components/ChatInput.svelte` | **Modify** — render thinking steps |
| `devtools/src/components/NodeDetail.svelte` | **Modify** — show reflection details |
