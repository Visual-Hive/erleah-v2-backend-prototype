# Erleah DevTools — Architecture

## Overview

A developer-facing debug & tuning UI for the Erleah 9-node LangGraph pipeline. Think **n8n meets LangSmith** — real-time workflow visualization, prompt editing, model A/B testing, and run comparison.

## Tech Stack

| Layer | Technology | Rationale |
|---|---|---|
| **Frontend** | Svelte 5 + Vite | Fast, minimal boilerplate, reactive stores for real-time updates |
| **Backend API** | FastAPI (existing) | Add `/api/debug/*` endpoints alongside existing `/api/chat/*` |
| **Real-time** | SSE (existing) | Enhanced events with debug metadata |
| **State** | Svelte stores (in-memory) | Session persistence only — no database needed |
| **Styling** | Tailwind CSS | Rapid UI development, dark theme |

## Pipeline Nodes (Current)

```
START
  → fetch_data            [no LLM]    Fetch user profile + history from Directus
  → update_profile?       [Sonnet]    Conditional: detect & save profile changes
  → generate_acknowledgment [Grok]    Quick contextual ack for UX
  → plan_queries          [Sonnet]    LLM plans search strategy (JSON output)
  → execute_queries       [no LLM]    Run planned queries against Qdrant
  → check_results         [no LLM]    Evaluate result quality, decide retry
  → relax_and_retry?      [no LLM]    Conditional: lower thresholds, retry search
  → generate_response     [Sonnet]    Stream final answer to user
  → evaluate              [Haiku]     Background quality scoring
END
```

### LLM-Calling Nodes

| Node | Current Model | System Prompt | Purpose |
|---|---|---|---|
| `plan_queries` | Claude Sonnet 4 | `PLAN_QUERIES_SYSTEM` | Produce JSON search plan |
| `generate_response` | Claude Sonnet 4 | `GENERATE_RESPONSE_SYSTEM` | Generate user-facing answer |
| `evaluate` | Claude Haiku 4.5 | `EVALUATE_SYSTEM` | Score response quality |
| `update_profile` | Claude Sonnet 4 | `PROFILE_DETECT_SYSTEM` + `PROFILE_UPDATE_SYSTEM` | Detect & merge profile updates |
| `generate_acknowledgment` | Grok 3 Mini | (inline prompt) | Quick contextual ack |

### Available Models

| Provider | Model | Speed | Quality | Cost | Best For |
|---|---|---|---|---|---|
| Anthropic | Claude Sonnet 4 | Medium | Excellent | $$$ | Response generation, planning |
| Anthropic | Claude Haiku 4.5 | Fast | Good | $ | Evaluation, simple tasks |
| Groq | Llama 3.3 70B | Very Fast | Good | $ | Planning, evaluation |
| Groq | Llama 3.1 8B | Ultra Fast | Decent | ¢ | Acknowledgments, simple eval |
| Groq | Mixtral 8x7B | Very Fast | Good | $ | Alternative for planning |
| xAI | Grok 3 Mini | Fast | Good | $ | Acknowledgments (current) |

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────┐
│                    Svelte DevTools App                    │
│                                                          │
│  ┌──────────┐  ┌──────────────┐  ┌───────────────────┐  │
│  │ Chat     │  │ Workflow     │  │ Config Panel      │  │
│  │ Input    │  │ Graph        │  │ - Prompt Editor   │  │
│  │          │  │ (n8n style)  │  │ - Model Selector  │  │
│  │          │  │              │  │ - Run History     │  │
│  └────┬─────┘  └──────┬───────┘  └────────┬──────────┘  │
│       │               │                    │             │
│       └───────────────┴────────────────────┘             │
│                        │                                 │
│                   Svelte Stores                          │
│            (pipeline, config, history)                    │
└────────────────────────┬─────────────────────────────────┘
                         │ SSE + REST
                         ▼
┌─────────────────────────────────────────────────────────┐
│                   FastAPI Backend                         │
│                                                          │
│  /api/chat/stream     → SSE with debug events            │
│  /api/debug/prompts   → GET/PUT system prompts           │
│  /api/debug/models    → GET/PUT model config per node    │
│  /api/debug/config    → GET full pipeline config         │
│                                                          │
│  ┌─────────────────────────────────────────────┐        │
│  │           LLM Registry                       │        │
│  │  node → { provider, model, prompt }          │        │
│  │  Runtime-swappable via API                   │        │
│  └─────────────────────────────────────────────┘        │
│                                                          │
│  ┌─────────────────────────────────────────────┐        │
│  │        LangGraph Pipeline (9 nodes)          │        │
│  │  Enhanced with debug event emission          │        │
│  └─────────────────────────────────────────────┘        │
└─────────────────────────────────────────────────────────┘
```

## SSE Event Schema (Enhanced)

Existing events are preserved for backward compatibility. New debug events are added:

```
# Existing (unchanged)
event: acknowledgment    data: {"message": "..."}
event: progress          data: {"node": "...", "message": "..."}
event: chunk             data: {"text": "..."}
event: done              data: {"trace_id": "...", "referenced_ids": [...]}
event: error             data: {"error": "...", "can_retry": true}

# New debug events
event: node_start        data: {"node": "plan_queries", "ts": 1234567890.123, 
                                 "input": {...}}
event: node_end          data: {"node": "plan_queries", "ts": 1234567891.456,
                                 "duration_ms": 1333, "output": {...},
                                 "llm": {"model": "claude-sonnet-4", 
                                         "input_tokens": 381, "output_tokens": 144,
                                         "cached_tokens": 0},
                                 "prompt_id": "plan_queries_v1"}
event: pipeline_summary  data: {"trace_id": "...", "total_ms": 17450,
                                 "nodes": [...], "quality_score": 0.85,
                                 "total_tokens": {"input": 961, "output": 542}}
```

## File Structure (New/Modified)

### Backend (Python)
```
src/
├── agent/
│   ├── llm.py              # MODIFIED: Use LLM registry
│   ├── llm_registry.py     # NEW: Runtime-configurable model registry
│   ├── graph.py             # MODIFIED: Emit debug events
│   └── prompts.py           # MODIFIED: Add prompt metadata
├── api/
│   └── debug.py             # NEW: Debug API endpoints
└── config.py                # MODIFIED: Add Groq config
```

### Frontend (Svelte)
```
devtools/
├── package.json
├── vite.config.js
├── index.html
├── src/
│   ├── App.svelte
│   ├── main.js
│   ├── app.css                  # Tailwind + dark theme
│   ├── lib/
│   │   ├── api.js               # REST + SSE client
│   │   └── stores/
│   │       ├── pipeline.js      # Current run state
│   │       ├── config.js        # Model/prompt config
│   │       └── history.js       # Session run history
│   └── components/
│       ├── WorkflowGraph.svelte
│       ├── NodeDetail.svelte
│       ├── ChatInput.svelte
│       ├── PromptEditor.svelte
│       ├── ModelSelector.svelte
│       ├── RunHistory.svelte
│       ├── RunComparison.svelte
│       └── Timeline.svelte
```

## Phases

| Phase | Scope | Effort | Dependency |
|---|---|---|---|
| **Phase 1** | Pipeline Visibility | ~2 days | None |
| **Phase 2** | Prompt Editor | ~1 day | Phase 1 |
| **Phase 3** | Model Selector + Groq | ~1.5 days | Phase 1 |
| **Phase 4** | Run Comparison | ~1.5 days | Phase 1 |

Phases 2, 3, 4 can be done in parallel after Phase 1.

## Design Principles

1. **Zero impact on production** — Debug features are additive. Existing SSE contract unchanged.
2. **Session-only persistence** — Run history lives in Svelte stores. Refresh = clean slate.
3. **Hot-swappable** — Models and prompts change at runtime without restart.
4. **Developer-first UX** — Dense, information-rich. Not a consumer UI.
