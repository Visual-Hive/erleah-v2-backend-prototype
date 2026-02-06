# Phase 1: Pipeline Visibility

## Goal
See every pipeline node execute in real-time with timing, data in/out, and token usage — like watching an n8n workflow run.

## Backend Changes

### 1.1 Enhanced SSE Debug Events
**File:** `src/agent/graph.py` — modify `stream_agent_response()`

Add two new SSE event types alongside existing ones:

```python
# Emit when a node starts
event: node_start
data: {
  "node": "plan_queries",
  "ts": 1234567890.123,
  "input": {
    "user_message": "Find AI sessions",
    "has_profile": true,
    "profile_summary": "Interests: AI, Python",
    "history_count": 3
  }
}

# Emit when a node completes
event: node_end
data: {
  "node": "plan_queries",
  "ts": 1234567891.456,
  "duration_ms": 1333,
  "output": {
    "intent": "find AI sessions",
    "query_mode": "hybrid",
    "planned_queries": [...]
  },
  "llm": {
    "model": "claude-sonnet-4-20250514",
    "input_tokens": 381,
    "output_tokens": 144,
    "cached_tokens": 0
  }
}

# Emit after evaluate completes
event: pipeline_summary
data: {
  "trace_id": "abc-123",
  "total_ms": 17450,
  "quality_score": 0.85,
  "nodes": [
    {"node": "fetch_data", "duration_ms": 140, "status": "ok"},
    {"node": "plan_queries", "duration_ms": 3920, "status": "ok", "model": "claude-sonnet-4"},
    ...
  ]
}
```

**Implementation approach:** Intercept `on_chain_start` and `on_chain_end` events from `graph.astream_events()` and extract the node state diffs.

### 1.2 Debug Mode Flag
**File:** `src/config.py`

Add: `debug_mode: bool = True` — when True, emit `node_start`/`node_end`/`pipeline_summary` events. When False, only emit existing events.

Pass `?debug=true` query param or always-on in dev.

### Files to Modify
- `src/agent/graph.py` — add debug event emission in `stream_agent_response()`
- `src/config.py` — add `debug_mode` setting

## Frontend: Svelte App Scaffold

### 1.3 Initialize Svelte + Vite Project
```bash
cd /Users/richardosborne/vscode_projects/erleah-backend
npm create vite@latest devtools -- --template svelte
cd devtools
npm install
npm install -D tailwindcss @tailwindcss/vite
```

### 1.4 Core Layout — `App.svelte`
Three-panel layout:
- **Left panel (30%):** Chat input + response stream
- **Center panel (40%):** Workflow graph visualization
- **Right panel (30%):** Node detail (click a node to inspect)

### 1.5 Svelte Stores — `src/lib/stores/pipeline.js`
```javascript
// Reactive store for current pipeline run
{
  traceId: "abc-123",
  status: "running", // idle | running | complete | error
  startedAt: 1234567890,
  nodes: {
    "fetch_data":    { status: "complete", duration_ms: 140, input: {...}, output: {...} },
    "plan_queries":  { status: "running",  startedAt: 1234567890, input: {...} },
    "execute_queries": { status: "waiting" },
    ...
  }
}
```

### 1.6 WorkflowGraph Component
Visual representation of the 9 nodes as boxes connected by arrows.

Each node box shows:
- Name
- Status icon (⏳ waiting, 🔵 running spinner, ✅ complete, ❌ error)
- Duration badge when complete
- Token count badge for LLM nodes
- Glow/highlight on the currently active node

Use CSS Grid or SVG for layout. Nodes arranged in a flow:
```
[fetch_data] → [update_profile?] → [acknowledgment] → [plan_queries]
                                                            ↓
[evaluate] ← [generate_response] ← [check_results] ← [execute_queries]
                                         ↕
                                   [relax_and_retry]
```

### 1.7 NodeDetail Component
When you click a node in the graph:
- **Input data**: Collapsible JSON tree
- **Output data**: Collapsible JSON tree
- **Duration**: X.XXs
- **LLM info** (if applicable): Model name, token counts
- **Status**: Waiting / Running / Complete / Error

### 1.8 ChatInput Component
- Text input + Send button
- Sends POST to `/api/chat/stream`
- Connects to SSE and feeds events into the pipeline store
- Shows streamed response text

### Files to Create
```
devtools/
├── package.json
├── vite.config.js
├── index.html
├── src/
│   ├── App.svelte
│   ├── main.js
│   ├── app.css
│   ├── lib/
│   │   ├── api.js
│   │   └── stores/
│   │       └── pipeline.js
│   └── components/
│       ├── WorkflowGraph.svelte
│       ├── NodeDetail.svelte
│       └── ChatInput.svelte
```

## Acceptance Criteria
- [ ] Send a message from the DevTools UI
- [ ] See each node light up in real-time as it executes
- [ ] See duration badge appear on each node when it completes
- [ ] See token counts on LLM nodes (plan_queries, generate_response, evaluate)
- [ ] Click any node to see its input/output data as JSON
- [ ] See the streamed response text in the left panel
- [ ] Pipeline summary appears after completion
