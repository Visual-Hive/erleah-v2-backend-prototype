# Erleah v2 Backend Prototype

## Critical: External Documentation

**ALWAYS read the full documentation repository before making architectural decisions:**
```
/home/ikniz/Work/Coding/AI_MachineLearning/central-assistant-docs/
```

This contains the complete system design docs (28 markdown files) covering:
- `current-system/` — n8n architecture, problems, secret sauce (multi-faceted vectorization)
- `python-system/` — Target architecture, state machine, caching, concurrency, monitoring, deployment
- `python-system/code-examples/` — Reference implementations for FastAPI, LangGraph, caching, services, testing
- `migration/` — Migration strategy, comparison, data migration, rollout plan, wins

Also read the in-repo dev-docs:
```
dev-docs/mini-assistant/
```

## Project Overview

AI-powered conference assistant backend. Migrating from n8n (low-code) to Python (FastAPI + LangGraph).

**Tech Stack:** FastAPI, LangGraph, Qdrant (vector DB), Directus (CMS/API), Redis (caching), Anthropic Claude (Sonnet + Haiku), OpenAI embeddings (text-embedding-3-small, 1536 dims)

## Architecture: 8-Node LangGraph Pipeline

```
START -> fetch_data_parallel
  -> [conditional: profile_needs_update?] -> update_profile (or skip)
  -> plan_queries (Sonnet -> structured JSON)
  -> execute_queries (parallel hybrid_search)
  -> check_results
  -> [conditional: needs_retry?] -> relax_and_retry -> (back to check_results)
  -> generate_response (Sonnet streaming -> SSE chunks)
  -> evaluate (Haiku, non-blocking, runs after 'done' sent)
  -> END
```

## Key Source Files

- `src/main.py` — FastAPI app, SSE streaming endpoints
- `src/agent/graph.py` — 8-node LangGraph wiring + stream_agent_response
- `src/agent/state.py` — AssistantState TypedDict
- `src/agent/llm.py` — Sonnet + Haiku instances
- `src/agent/prompts.py` — All system prompts
- `src/agent/nodes/` — 8 node implementations (fetch_data, update_profile, plan_queries, execute_queries, check_results, relax_and_retry, generate_response, evaluate)
- `src/search/faceted.py` — Multi-faceted search algorithm (the "secret sauce")
- `src/services/` — Directus, Qdrant, embedding clients
- `src/config.py` — Settings via pydantic-settings
- `tests/test_nodes.py` — 19 unit tests for all nodes

## Secret Sauce: Multi-Faceted Vectorization

1 entity -> 8 faceted vector records (not 1 monolithic embedding). Paired facet matching (e.g. `products_i_want_to_buy` <-> `products_i_want_to_sell`). Scoring: `score = (breadth x 0.4) + (depth x 0.6)`. Result: user satisfaction 63% -> 89%.

## 3 Query Modes

- `specific` — Traditional vector search + filters (keyword queries)
- `profile` — Multi-faceted search using user profile facets (recommendation)
- `hybrid` — Both combined (most common)

## SSE Event Types

- `acknowledgment` — Sent immediately on request
- `progress` — When each node starts (node name)
- `chunk` — Streamed response tokens (from generate_response only)
- `done` — After generate_response completes (before evaluate finishes)
- `error` — On failures

## Running

```bash
# Server
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Tests
pytest tests/test_nodes.py -v

# Test SSE
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "Where can I get free coffee?", "user_context": {"conference_id": "conf-2024"}}'
```
