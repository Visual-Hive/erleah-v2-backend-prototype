# Phase 4: Run Comparison

## Goal
Compare pipeline runs side-by-side — same question with different models/prompts. See timing, quality, and output differences at a glance.

## Depends On
Phase 1 (pipeline visibility + Svelte app scaffold)

## No Backend Changes Required
All run data is already captured via SSE debug events (Phase 1). This phase is **frontend-only** — runs are stored in Svelte stores (session memory).

## Frontend Components

### 4.1 Run History Store
**New file:** `devtools/src/lib/stores/history.js`

Stores completed pipeline runs in session memory:

```javascript
// Array of completed runs, newest first
[
  {
    id: "run-1",
    traceId: "abc-123",
    timestamp: 1234567890,
    message: "Find AI sessions",
    totalMs: 17450,
    qualityScore: 0.85,
    responseText: "I found 5 AI sessions...",
    modelConfig: {
      "plan_queries": "claude-sonnet-4",
      "generate_response": "claude-sonnet-4",
      "evaluate": "claude-haiku-4.5"
    },
    promptVersions: {
      "plan_queries": 1,
      "generate_response": 2
    },
    nodes: [
      { node: "fetch_data", duration_ms: 140, status: "ok", input: {...}, output: {...} },
      { node: "plan_queries", duration_ms: 3920, status: "ok", 
        llm: { model: "claude-sonnet-4", input_tokens: 381, output_tokens: 144 },
        input: {...}, output: {...} },
      ...
    ],
    totalTokens: { input: 961, output: 542, cached: 0 }
  },
  ...
]
```

Max 50 runs kept in memory. Cleared on page refresh (session-only).

### 4.2 RunHistory Component
**New file:** `devtools/src/components/RunHistory.svelte`

A table/list of past runs in the current session:

| # | Time | Message | Duration | Quality | Models | Actions |
|---|---|---|---|---|---|---|
| 3 | 8:12pm | Find AI sessions | 17.4s | 0.85 | S/S/H | 🔍 Compare |
| 2 | 8:10pm | Find AI sessions | 4.2s | 0.72 | G/G/G | 🔍 Compare |
| 1 | 8:08pm | What can you help with? | 14.1s | 0.85 | S/S/H | 🔍 Compare |

Features:
- Click a row to load its data into the workflow graph (replay visualization)
- Checkbox to select two runs for comparison
- **Compare** button when 2 runs selected
- **Replay** button to re-send the same message with current config
- **Clear History** button
- Filter/search by message text

### 4.3 RunComparison Component
**New file:** `devtools/src/components/RunComparison.svelte`

Side-by-side comparison of two selected runs:

```
┌──────────────────────────┬──────────────────────────┐
│       Run A (17.4s)      │       Run B (4.2s)       │
│   Sonnet / Sonnet / Haiku│  Groq / Groq / Groq      │
├──────────────────────────┼──────────────────────────┤
│ fetch_data:     0.14s    │ fetch_data:     0.14s    │
│ acknowledgment: 0.71s    │ acknowledgment: 0.71s    │
│ plan_queries:   3.92s ⚠️ │ plan_queries:   0.31s ✨ │
│ execute_queries:3.57s    │ execute_queries:3.57s    │
│ check_results:  0.00s    │ check_results:  0.00s    │
│ gen_response:   4.87s ⚠️ │ gen_response:   0.42s ✨ │
│ evaluate:       3.40s    │ evaluate:       0.28s ✨ │
├──────────────────────────┼──────────────────────────┤
│ Quality: 0.85            │ Quality: 0.72            │
│ Tokens: 961 in / 542 out│ Tokens: 890 in / 498 out │
├──────────────────────────┼──────────────────────────┤
│ Response:                │ Response:                │
│ "I found 5 AI sessions   │ "Here are some AI        │
│  that match your..."     │  sessions I found..."    │
└──────────────────────────┴──────────────────────────┘
```

Features:
- **Timing comparison** with visual bars (Gantt-style)
- **Green/red highlighting** for faster/slower nodes
- **Quality score comparison**
- **Token usage comparison**
- **Response text diff** (highlight differences)
- **Model labels** per node showing which model was used

### 4.4 Timeline Component
**New file:** `devtools/src/components/Timeline.svelte`

Gantt-chart-like horizontal bar chart showing time spent in each node:

```
fetch_data       ██ 0.14s
acknowledgment   █████ 0.71s
plan_queries     ██████████████████████████ 3.92s
execute_queries  ████████████████████████ 3.57s
check_results    █ 0.00s
gen_response     ██████████████████████████████████ 4.87s
evaluate         ██████████████████████ 3.40s
                 |----|----|----|----|----|----|
                 0s   3s   6s   9s  12s  15s  18s
```

Features:
- Color-coded by node type (LLM = blue, search = green, logic = gray)
- Hover to see exact timing
- Overlay two runs for visual comparison
- LLM nodes show token count inside the bar

### 4.5 Replay Functionality
**No new backend needed** — just re-send the same message via existing `/api/chat/stream`.

The Replay button:
1. Takes the message from a previous run
2. Sends it to the current backend (with current model/prompt config)
3. Stores the result as a new run
4. Auto-selects both runs for comparison

This is the core A/B testing loop:
1. Run with Sonnet → see results
2. Switch evaluate to Groq → Replay → compare

### Files to Create
- `devtools/src/lib/stores/history.js` — **NEW**
- `devtools/src/components/RunHistory.svelte` — **NEW**
- `devtools/src/components/RunComparison.svelte` — **NEW**
- `devtools/src/components/Timeline.svelte` — **NEW**

## Acceptance Criteria
- [ ] Each completed pipeline run appears in the run history list
- [ ] Click a run to view its full data in the workflow graph
- [ ] Select two runs and click Compare for side-by-side view
- [ ] See timing differences highlighted (green = faster)
- [ ] See response text from both runs
- [ ] Timeline/Gantt chart shows time breakdown
- [ ] Replay button re-runs same message with current config
- [ ] History clears on page refresh (session-only)
