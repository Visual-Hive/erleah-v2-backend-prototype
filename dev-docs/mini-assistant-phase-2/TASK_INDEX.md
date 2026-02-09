# Task Series: n8n Replacement — Final Push
## Erleah v2 Backend

**Created:** February 2026  
**Context:** Post-audit tasks to take the Python backend from working prototype to production n8n replacement.  
**Branch:** `devtools`

---

## Task Order & Dependencies

```
TASK-01: Graceful Failure System ←── foundational, do first
   ↓
TASK-02: Directus Streaming Fallback (WebSocket/polling mode)
   ↓
TASK-03: Conversation Context System (replaces profile system)
   ↓
TASK-04: Real Directus + Qdrant Integration
   ↓
TASK-05: Production Hardening (rate limits, circuit breakers, health, CORS)
   ↓
TASK-06: Caching Layers (embedding + query result)
```

### Why This Order

1. **TASK-01 first** because every subsequent task needs the failure system. When we wire up real Directus/Qdrant, things will break — the failure system ensures the user always gets a coherent response regardless.
2. **TASK-02 early** because it unblocks frontend testing against the real backend without requiring SSE changes on the frontend.
3. **TASK-03 before TASK-04** because we need to define what context data flows into the pipeline before we wire up the real data sources.
4. **TASK-04** is the big integration task — connecting to the playground Qdrant and Directus.
5. **TASK-05** after integration works, because hardening is about protecting a working system.
6. **TASK-06 last** because caching is optimization — the system should work correctly first.

---

## Scope Decisions

These decisions simplify the first production deployment:

- **No profile system** — anonymous users only. Conversation history is the sole context.
- **No profile update detection/execution** — skip `update_profile` node entirely for now.
- **Frontend stays on WebSocket/Directus** — backend writes chunks to Directus messages, no SSE needed on frontend.
- **SSE stays for devtools** — the debug SSE stream remains for the devtools GUI.
- **Graceful failure is non-negotiable** — the agent must always reply with *something*.

---

## Files

| Task | File | Effort | Priority |
|------|------|--------|----------|
| TASK-01 | [TASK-01_GRACEFUL_FAILURE.md](./TASK-01_GRACEFUL_FAILURE.md) | 1-2 days | 🔴 Critical |
| TASK-02 | [TASK-02_DIRECTUS_STREAMING_FALLBACK.md](./TASK-02_DIRECTUS_STREAMING_FALLBACK.md) | 1 day | 🔴 Critical |
| TASK-03 | [TASK-03_CONVERSATION_CONTEXT.md](./TASK-03_CONVERSATION_CONTEXT.md) | 1 day | 🔴 Critical |
| TASK-04 | [TASK-04_DIRECTUS_QDRANT_INTEGRATION.md](./TASK-04_DIRECTUS_QDRANT_INTEGRATION.md) | 2-3 days | 🔴 Critical |
| TASK-05 | [TASK-05_PRODUCTION_HARDENING.md](./TASK-05_PRODUCTION_HARDENING.md) | 2 days | 🟡 Important |
| TASK-06 | [TASK-06_CACHING_LAYERS.md](./TASK-06_CACHING_LAYERS.md) | 1-2 days | 🟡 Important |

**Total estimated effort:** 8-11 days
