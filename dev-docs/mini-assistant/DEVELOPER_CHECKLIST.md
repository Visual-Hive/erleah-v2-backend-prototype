# Developer Checklist
## Mini-Assistant Implementation Progress Tracker

Use this checklist to track your progress. Check off items as you complete them.

---

## Week 1: Prototype (Days 1-10)

### Phase 0: Project Setup (Days 1-2)
- [ ] Clone/create repository
- [ ] Set up Python 3.11+ with Poetry
- [ ] Create `pyproject.toml` with all dependencies
- [ ] Create project directory structure
- [ ] Create `.env.example` with all required variables
- [ ] Create `.env` with actual credentials
- [ ] Create `docker-compose.yml` for local dev
- [ ] Start local Qdrant and Redis with `docker-compose up`
- [ ] Create `src/config/settings.py` with Pydantic settings
- [ ] Create basic FastAPI app in `src/api/main.py`
- [ ] Implement `GET /health` endpoint
- [ ] Verify app starts: `uvicorn src.api.main:app --reload`
- [ ] Test health endpoint: `curl http://localhost:8000/health`

**Checkpoint:** App runs locally, health endpoint works ✅

---

### Phase 1: Directus Integration (Days 2-3)
- [ ] Create `src/services/directus.py`
- [ ] Implement `DirectusClient` class with httpx
- [ ] Implement `get_conversation(conversation_id)`
- [ ] Implement `get_conversation_messages(conversation_id, limit)`
- [ ] Implement `create_message(conversation_id, role, text, status)`
- [ ] Implement `update_message_text(message_id, text)`
- [ ] Implement `complete_message(message_id, final_text, metadata)`
- [ ] Implement `get_conference(conference_id)`
- [ ] Implement `get_sessions(conference_id)`
- [ ] Implement `get_exhibitors(conference_id)`
- [ ] Implement `get_speakers(conference_id)`
- [ ] Test connection to Directus instance
- [ ] Test fetching a real conversation
- [ ] Test creating and updating a message

**Checkpoint:** Can read/write to Directus ✅

---

### Phase 2: Qdrant & Embeddings (Days 3-5)
- [ ] Create `src/services/qdrant.py`
- [ ] Implement `QdrantService` class
- [ ] Implement `ensure_collections()` to create all 6 collections
- [ ] Implement `search(collection, query_vector, filters)`
- [ ] Implement `search_faceted(entity_type, query_vector, facet_key)`
- [ ] Implement `upsert_points(collection, points)`
- [ ] Create `src/services/embedding.py`
- [ ] Implement `EmbeddingService` with OpenAI
- [ ] Implement `embed_text(text)`
- [ ] Implement `embed_batch(texts)`
- [ ] Create `src/search/faceted.py`
- [ ] Implement `faceted_search(entity_type, query, conference_id)`
- [ ] Implement `hybrid_search(entity_type, query, conference_id, use_faceted)`
- [ ] Create `scripts/ingest_exhibitors.py`
- [ ] Create `scripts/ingest_sessions.py`
- [ ] Create `scripts/ingest_speakers.py`
- [ ] Run ingestion for test conference
- [ ] Verify data in Qdrant (use Qdrant dashboard: http://localhost:6333/dashboard)
- [ ] Test search returns relevant results

**Checkpoint:** Qdrant populated, search works ✅

---

### Phase 3: LangGraph Agent (Days 5-7)
- [ ] Create `src/agent/state.py` with `AgentState` definition
- [ ] Create `src/agent/nodes/understand.py`
- [ ] Create `src/agent/nodes/plan.py`
- [ ] Create `src/agent/nodes/execute.py`
- [ ] Create `src/agent/nodes/reflect.py`
- [ ] Create `src/agent/nodes/respond.py`
- [ ] Create `src/agent/graph.py` with LangGraph workflow
- [ ] Implement conditional edge (`should_continue`)
- [ ] Compile and test graph with simple query
- [ ] Verify streaming updates reach Directus
- [ ] Test full agent flow end-to-end

**Checkpoint:** Agent processes queries, streams to Directus ✅

---

### Phase 4: Tools (Days 7-9)
- [ ] Create `src/tools/base.py` with `BaseTool` class
- [ ] Create `src/tools/__init__.py` with tool registry
- [ ] Create `src/tools/session_search.py`
  - [ ] Implement master search mode
  - [ ] Implement faceted search mode
  - [ ] Test with sample queries
- [ ] Create `src/tools/exhibitor_search.py`
  - [ ] Implement master search mode
  - [ ] Implement faceted search mode
  - [ ] Test with sample queries
- [ ] Create `src/tools/speaker_search.py`
  - [ ] Implement master search mode
  - [ ] Implement faceted search mode
  - [ ] Test with sample queries
- [ ] Create `src/tools/conference_info.py`
  - [ ] Implement general info retrieval
  - [ ] Test with sample queries
- [ ] Register all tools in registry
- [ ] Verify agent uses correct tools for different intents

**Checkpoint:** All tools implemented and working ✅

---

### Phase 5: API & Integration (Days 9-10)
- [ ] Create `src/api/routes/chat.py`
- [ ] Implement `POST /api/chat` endpoint
- [ ] Create `src/models/requests.py` with Pydantic models
- [ ] Create `src/models/responses.py` with Pydantic models
- [ ] Add request validation
- [ ] Add error handling
- [ ] Add CORS middleware
- [ ] Create `src/api/middleware/error_handler.py`
- [ ] Test endpoint with cURL
- [ ] Test full flow: send message → see response in Directus
- [ ] Test with frontend widget (if available)

**🎉 PROTOTYPE COMPLETE ✅**

---

## Weeks 2-3: Production Ready (Days 10-15)

### Phase 6: Production Hardening (Days 10-14)
- [ ] Create `src/utils/logging.py` with structlog
- [ ] Add structured logging throughout codebase
- [ ] Add request trace IDs
- [ ] Set up Sentry for error tracking
- [ ] Create `/metrics` endpoint for Prometheus
- [ ] Add retry logic to Directus client
- [ ] Add retry logic to Qdrant client
- [ ] Add retry logic to Anthropic calls
- [ ] Add timeout handling everywhere
- [ ] Set up Redis caching for conference data
- [ ] Create `tests/conftest.py` with fixtures
- [ ] Write unit tests for faceted search
- [ ] Write unit tests for tools
- [ ] Write integration tests for chat endpoint
- [ ] Achieve >70% test coverage
- [ ] Run load test with 10 concurrent users

**Checkpoint:** System is robust and observable ✅

---

### Phase 7: Deployment (Days 14-15)
- [ ] Create production `Dockerfile`
- [ ] Test Docker build locally
- [ ] Test Docker container runs correctly
- [ ] Set up Azure Container Registry (ACR)
- [ ] Push image to ACR
- [ ] Create Azure Container App
- [ ] Configure environment variables/secrets
- [ ] Deploy container
- [ ] Configure custom domain (if needed)
- [ ] Set up SSL certificate
- [ ] Test production health endpoint
- [ ] Test production chat endpoint
- [ ] Run smoke tests
- [ ] Monitor logs for errors
- [ ] Verify metrics are collected

**🚀 PRODUCTION READY ✅**

---

## Quick Reference Commands

### Local Development
```bash
# Start dependencies
docker-compose up -d qdrant redis

# Run API
uvicorn src.api.main:app --reload --port 8000

# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

### Ingestion
```bash
# Ingest all data for a conference
python scripts/ingest_all.py <conference_id>
```

### Docker
```bash
# Build
docker build -t erleah-mini-assistant:latest .

# Run
docker run -p 8000:8000 --env-file .env erleah-mini-assistant:latest

# Push to ACR
docker tag erleah-mini-assistant:latest youracr.azurecr.io/erleah-mini-assistant:latest
docker push youracr.azurecr.io/erleah-mini-assistant:latest
```

### Testing
```bash
# Health check
curl http://localhost:8000/health

# Chat endpoint
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": "...", "message_id": "...", "conference_id": "..."}'
```

---

## Key Files Quick Reference

| File | Purpose |
|------|---------|
| `src/config/settings.py` | Environment configuration |
| `src/api/main.py` | FastAPI application |
| `src/api/routes/chat.py` | Chat endpoint |
| `src/services/directus.py` | Directus API client |
| `src/services/qdrant.py` | Qdrant vector operations |
| `src/services/embedding.py` | OpenAI embeddings |
| `src/agent/graph.py` | LangGraph workflow |
| `src/agent/state.py` | Agent state definition |
| `src/search/faceted.py` | Multi-faceted search logic |
| `src/tools/*.py` | Individual tools |

---

## Troubleshooting

### Common Issues

**"Connection refused" to Qdrant**
- Check if Qdrant is running: `docker-compose ps`
- Check URL in `.env`: should be `http://localhost:6333` for local dev

**"401 Unauthorized" from Directus**
- Check `DIRECTUS_API_KEY` in `.env`
- Verify API key has correct permissions

**"No results" from search**
- Verify data was ingested: check Qdrant dashboard
- Check `conference_id` matches ingested data
- Try lowering `score_threshold` in search

**Agent loops infinitely**
- Check `max_iterations` in state
- Verify `reflect` node properly sets `needs_more_info`

**Streaming doesn't update in frontend**
- Verify WebSocket connection to Directus
- Check message ID subscription is correct
- Verify backend is actually updating `messageText`

---

## Questions?

Review the documentation first:
1. [MINI_ASSISTANT_ROADMAP.md](./MINI_ASSISTANT_ROADMAP.md) - Overall plan
2. [DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md) - Implementation details
3. [FACET_DEFINITIONS.md](./FACET_DEFINITIONS.md) - Multi-faceted search
4. [API_CONTRACT.md](./API_CONTRACT.md) - Frontend/backend interface

Still stuck? Ask before spending too much time on any single issue.
