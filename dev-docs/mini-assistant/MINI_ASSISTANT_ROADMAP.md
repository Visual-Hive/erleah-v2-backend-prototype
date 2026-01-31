# Mini-Assistant Roadmap
## Erleah v2 Backend - Phase 1: Production Mini-Assistant

**Target:** Conference widget for visitors/attendees to ask questions about sessions, exhibitors, speakers, and general conference information.

**Timeline:**
- **Week 1:** Working prototype (end-to-end flow)
- **Weeks 2-3:** Production-ready deployment

**What's NOT in scope (deferred to Phase 2+):**
- User authentication/login
- User profiles and personalization
- Attendee search/matchmaking
- Navigation and maps
- Schedule management
- Networking features

---

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                     FRONTEND (Widget)                           │
│  1. Creates conversation (source='mini', user='Public User')    │
│  2. Creates user message                                        │
│  3. Calls backend API                                           │
│  4. WebSocket to Directus for message updates                   │
└──────────────────────────┬──────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                  ERLEAH BACKEND (FastAPI)                       │
│                                                                 │
│  POST /api/chat                                                 │
│  ├── Receives: conversation_id, message_id, conference_id      │
│  ├── Fetches conversation context from Directus                │
│  ├── Runs LangGraph agent                                       │
│  ├── Updates message.messageText with chunks (DIY streaming)   │
│  └── Returns: success status                                    │
│                                                                 │
│  LangGraph Agent:                                               │
│  ┌─────────┐   ┌──────┐   ┌─────────┐   ┌─────────┐   ┌───────┐│
│  │Understand│──▶│ Plan │──▶│ Execute │──▶│ Reflect │──▶│Respond││
│  └─────────┘   └──────┘   └─────────┘   └─────────┘   └───────┘│
│                               │              │                  │
│                               ▼              │                  │
│                          ┌─────────┐         │                  │
│                          │  Tools  │◀────────┘                  │
│                          └─────────┘                            │
└──────────────────────────┬──────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌───────────┐   ┌───────────┐   ┌───────────┐
    │ Directus  │   │  Qdrant   │   │ Anthropic │
    │ (Data +   │   │ (Vector   │   │  Claude   │
    │ Messages) │   │  Search)  │   │  Sonnet   │
    └───────────┘   └───────────┘   └───────────┘
```

---

## Qdrant Collections (6 Total)

| Collection | Purpose | Facets |
|------------|---------|--------|
| `sessions_master` | Full session profiles for specific queries | N/A |
| `sessions_facets` | Multi-faceted session records | 6 facets |
| `exhibitors_master` | Full exhibitor profiles for specific queries | N/A |
| `exhibitors_facets` | Multi-faceted exhibitor records | 6 facets |
| `speakers_master` | Full speaker profiles for specific queries | N/A |
| `speakers_facets` | Multi-faceted speaker records | 5 facets |

→ See [FACET_DEFINITIONS.md](./FACET_DEFINITIONS.md) for detailed facet configurations.

---

## Phase Breakdown

### Phase 0: Project Setup (Days 1-2)
**Goal:** Developer can run the project locally

| Task | Description | Acceptance Criteria |
|------|-------------|---------------------|
| 0.1 | Initialize Python project with Poetry/pip | `pyproject.toml` or `requirements.txt` exists |
| 0.2 | Create project structure | All directories created per spec |
| 0.3 | Set up configuration management | `.env.example`, Pydantic settings |
| 0.4 | Docker Compose for local dev | Qdrant + Redis running locally |
| 0.5 | Connect to existing Directus | Can fetch conference data |
| 0.6 | Basic health endpoint | `GET /health` returns 200 |

**Deliverables:**
- Project runs with `docker-compose up`
- Health endpoint accessible at `http://localhost:8000/health`

---

### Phase 1: Directus Integration (Days 2-3)
**Goal:** Read/write conversations and messages

| Task | Description | Acceptance Criteria |
|------|-------------|---------------------|
| 1.1 | Directus client service | Async client with connection pooling |
| 1.2 | Fetch conversation by ID | Returns conversation with messages |
| 1.3 | Fetch conference data | Sessions, exhibitors, speakers |
| 1.4 | Create assistant message | New message with role='assistant' |
| 1.5 | Update message text (streaming) | Append chunks to messageText field |
| 1.6 | Mark message complete | Set status='completed' |

**Deliverables:**
- Can read existing conversation context
- Can create and update messages in Directus

---

### Phase 2: Qdrant Setup & Embeddings (Days 3-5)
**Goal:** Multi-faceted collections populated with conference data

| Task | Description | Acceptance Criteria |
|------|-------------|---------------------|
| 2.1 | Qdrant client service | Async client with retry logic |
| 2.2 | Create collection schemas | 6 collections with correct config |
| 2.3 | Embedding service | OpenAI text-embedding-3-small |
| 2.4 | Sessions ingestion script | Master + faceted records |
| 2.5 | Exhibitors ingestion script | Master + faceted records |
| 2.6 | Speakers ingestion script | Master + faceted records |
| 2.7 | Verify embeddings | Test search returns relevant results |

**Deliverables:**
- All 6 Qdrant collections populated
- Can search each collection successfully

---

### Phase 3: Core Agent (Days 5-7)
**Goal:** LangGraph agent processes queries end-to-end

| Task | Description | Acceptance Criteria |
|------|-------------|---------------------|
| 3.1 | Agent state definition | Pydantic model for AgentState |
| 3.2 | Understand node | Classifies intent, extracts entities |
| 3.3 | Plan node | Determines which tools to use |
| 3.4 | Execute node | Runs tools, collects results |
| 3.5 | Reflect node | Checks if more info needed |
| 3.6 | Respond node | Generates final response |
| 3.7 | Graph compilation | StateGraph with conditional edges |
| 3.8 | Streaming integration | Updates Directus during response |

**Deliverables:**
- Agent processes query and returns response
- Response streams to Directus message

---

### Phase 4: Tools Implementation (Days 7-9)
**Goal:** All search tools working with multi-faceted logic

| Task | Description | Acceptance Criteria |
|------|-------------|---------------------|
| 4.1 | Base tool class | Standard interface for all tools |
| 4.2 | SessionSearchTool | Master + faceted search |
| 4.3 | ExhibitorSearchTool | Master + faceted search |
| 4.4 | SpeakerSearchTool | Master + faceted search |
| 4.5 | ConferenceInfoTool | General conference queries |
| 4.6 | Tool registry | Tools available to agent |
| 4.7 | Result formatting | Consistent output format |

**Deliverables:**
- All tools return relevant results
- Agent selects appropriate tools

---

### Phase 5: API & Integration (Days 9-10)
**Goal:** Frontend can call backend successfully

| Task | Description | Acceptance Criteria |
|------|-------------|---------------------|
| 5.1 | Chat endpoint | `POST /api/chat` |
| 5.2 | Request validation | Pydantic models for input |
| 5.3 | Error handling | Graceful errors, user-friendly messages |
| 5.4 | CORS configuration | Widget can call API |
| 5.5 | Rate limiting | Basic protection |
| 5.6 | End-to-end test | Full flow works |

**Deliverables:**
- Widget can send message and see response
- **PROTOTYPE COMPLETE** ✅

---

### Phase 6: Production Hardening (Days 10-14)
**Goal:** Ready for production deployment

| Task | Description | Acceptance Criteria |
|------|-------------|---------------------|
| 6.1 | Logging (structured) | JSON logs with trace IDs |
| 6.2 | Error tracking | Sentry integration |
| 6.3 | Metrics endpoint | `/metrics` for monitoring |
| 6.4 | Retry logic | Exponential backoff for API calls |
| 6.5 | Timeout handling | No hanging requests |
| 6.6 | Caching | Redis for conference data |
| 6.7 | Unit tests | Core functions covered |
| 6.8 | Integration tests | End-to-end flows |

**Deliverables:**
- System handles errors gracefully
- Observable via logs and metrics

---

### Phase 7: Deployment (Days 14-15)
**Goal:** Running on Azure Container App

| Task | Description | Acceptance Criteria |
|------|-------------|---------------------|
| 7.1 | Production Dockerfile | Multi-stage, optimized |
| 7.2 | Azure Container App setup | Config and deployment |
| 7.3 | Environment variables | Secrets configured |
| 7.4 | Health checks | Azure monitors health |
| 7.5 | DNS/SSL | Accessible via HTTPS |
| 7.6 | Smoke tests | Production works |

**Deliverables:**
- Mini-assistant live in production
- **PRODUCTION READY** ✅

---

## Success Criteria

### Week 1 (Prototype)
- [ ] Agent processes queries end-to-end
- [ ] Multi-faceted search returns relevant results
- [ ] Response streams to Directus message
- [ ] Frontend widget displays responses

### Weeks 2-3 (Production)
- [ ] Deployed to Azure Container App
- [ ] Handles errors gracefully
- [ ] Logs and metrics available
- [ ] Passes load testing (10+ concurrent users)
- [ ] Response time < 10s for typical queries

---

## Key Files to Create

```
erleah-v2-backend/
├── src/
│   ├── api/
│   │   ├── __init__.py
│   │   ├── main.py              # FastAPI app
│   │   ├── routes/
│   │   │   ├── __init__.py
│   │   │   ├── chat.py          # POST /api/chat
│   │   │   └── health.py        # GET /health
│   │   └── middleware/
│   │       ├── __init__.py
│   │       └── error_handler.py
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── graph.py             # LangGraph definition
│   │   ├── state.py             # AgentState model
│   │   └── nodes/
│   │       ├── __init__.py
│   │       ├── understand.py
│   │       ├── plan.py
│   │       ├── execute.py
│   │       ├── reflect.py
│   │       └── respond.py
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py              # BaseTool class
│   │   ├── session_search.py
│   │   ├── exhibitor_search.py
│   │   ├── speaker_search.py
│   │   └── conference_info.py
│   ├── services/
│   │   ├── __init__.py
│   │   ├── directus.py          # Directus client
│   │   ├── qdrant.py            # Qdrant client
│   │   ├── embedding.py         # OpenAI embeddings
│   │   └── anthropic.py         # Claude client
│   ├── search/
│   │   ├── __init__.py
│   │   ├── faceted.py           # Multi-faceted search logic
│   │   └── scoring.py           # Result aggregation
│   ├── models/
│   │   ├── __init__.py
│   │   ├── requests.py          # API request models
│   │   ├── responses.py         # API response models
│   │   └── entities.py          # Session, Exhibitor, Speaker
│   ├── config/
│   │   ├── __init__.py
│   │   └── settings.py          # Pydantic settings
│   └── utils/
│       ├── __init__.py
│       └── logging.py           # Structured logging
├── scripts/
│   ├── ingest_sessions.py
│   ├── ingest_exhibitors.py
│   └── ingest_speakers.py
├── tests/
│   ├── unit/
│   ├── integration/
│   └── conftest.py
├── docker-compose.yml
├── Dockerfile
├── pyproject.toml
├── .env.example
└── README.md
```

---

## Next Steps

1. Read [DEVELOPER_GUIDE.md](./DEVELOPER_GUIDE.md) for detailed implementation instructions
2. Read [FACET_DEFINITIONS.md](./FACET_DEFINITIONS.md) for multi-faceted search configuration
3. Read [API_CONTRACT.md](./API_CONTRACT.md) for frontend ↔ backend interface
4. Start with Phase 0: Project Setup

---

**Questions?** Reach out before starting if anything is unclear.
