# Erleah Backend - AI Conference Assistant

**Agentic backend** powered by LangGraph and Anthropic Claude Sonnet 4.

## Features

- 🧠 **Agentic Reasoning** - Multi-step planning, reflection, tool orchestration
- 👁️ **Vision Capabilities** - Analyze conference maps and floor plans
- ⚡ **Real-time Streaming** - SSE for progressive responses
- 🔍 **Vector Search** - Semantic search for attendees, sessions, exhibitors
- 🛠️ **50+ Tools** - Extensible tool system for any conference task
- 💾 **Prompt Caching** - 90% cost savings on repeated queries

## Quick Start

```bash
# One command to start everything (backend + DevTools GUI):
make dev
```

That's it! This starts:
- **Backend** → http://localhost:8000 (FastAPI + Swagger at /docs)
- **DevTools** → http://localhost:5174 (Svelte GUI for pipeline inspection)

Press `Ctrl+C` to stop both servers.

### First-Time Setup

```bash
# 1. Install dependencies
uv sync                      # Python backend
cd devtools && npm install   # DevTools frontend

# 2. Configure environment
cp .env.example .env         # Then edit .env with your API keys

# 3. Start databases
make db                      # Docker: PostgreSQL, Redis, Qdrant

# 4. Start developing
make dev                     # Backend + DevTools
```

### All Commands

| Command | Description |
|---------|-------------|
| `make dev` | Start backend + DevTools (most common) |
| `make backend` | Start backend only (FastAPI on :8000) |
| `make devtools` | Start DevTools only (Svelte on :5174) |
| `make test` | Run all tests |
| `make db` | Start Docker databases |
| `make db-stop` | Stop Docker databases |
| `make install` | Install Python dependencies |
| `make install-devtools` | Install DevTools npm dependencies |
| `make setup` | First-time full setup |

You can also use the script directly: `./scripts/dev.sh [backend|devtools|all]`

### Prerequisites

- Python 3.11+ with [uv](https://github.com/astral-sh/uv)
- Node.js 18+ (for DevTools)
- Docker (for PostgreSQL, Redis, Qdrant)

## Project Structure

```
erleah-backend/
├── src/
│   ├── main.py              # FastAPI app entry point
│   ├── config.py            # Settings (from .env)
│   ├── agent/
│   │   ├── graph.py         # LangGraph agent definition
│   │   └── state.py         # Agent state schema
│   ├── tools/
│   │   ├── base.py          # Base tool class
│   │   ├── vector_search.py # Semantic search tool
│   │   └── ...              # More tools here
│   ├── db/
│   │   ├── postgres.py      # PostgreSQL connection
│   │   └── qdrant.py        # Qdrant vector DB
│   └── api/
│       └── routes.py        # API endpoints
├── tests/                   # Test suite
├── .clinerules             # Cline AI development rules
├── pyproject.toml          # Project metadata & deps
└── docker-compose.yml      # Local dev services
```

## API Endpoints

### Chat (SSE Streaming)

```bash
POST /api/chat/stream

# Request
{
  "message": "Find Python developers attending the conference",
  "user_context": {
    "user_id": "user-123",
    "location": "Hall A"
  }
}

# Response (SSE stream)
event: thinking
data: {"step": "planning", "plan": ["search_attendees", "filter_skills"]}

event: tool_execution
data: {"tool": "vector_search", "status": "running"}

event: message
data: {"token": "I"}

event: message
data: {"token": " found"}

event: done
data: {"status": "complete"}
```

### Health Check

```bash
GET /health

# Response
{
  "status": "healthy",
  "version": "0.1.0"
}
```

## Development with Cline

This project is designed for **vibe coding** with Cline AI assistant.

### Getting Started with Cline

1. Open project in VSCode
2. Ensure Cline extension is installed
3. Open `.clinerules` to see development guidelines
4. Start chatting with Cline to build features!

### Example Prompts for Cline

**Add a new tool:**
> "Create a tool that calculates the optimal route between two locations on the conference map"

**Extend the agent:**
> "Add a reflection step where the agent evaluates if it has enough info to answer"

**Fix a bug:**
> "The vector search is returning irrelevant results, can you improve the query?"

**Add tests:**
> "Write tests for the map navigation tool"

Cline will follow the patterns in `.clinerules` automatically.

## Adding a New Tool

Tools are how the agent interacts with the world. Here's the pattern:

### 1. Create Tool File

```bash
touch src/tools/my_new_tool.py
```

### 2. Implement Tool

```python
from langchain.tools import BaseTool
from pydantic import Field

class MyNewTool(BaseTool):
    name = "my_new_tool"
    description = """
    Clear description for the LLM to understand when to use this.
    
    Example: Use this when the user asks about X or needs to do Y.
    """
    
    location: str = Field(description="The location to process")
    
    async def _arun(self, location: str) -> dict:
        # Your implementation here
        result = await do_something(location)
        return {"success": True, "data": result}
```

### 3. Register Tool

Add to `src/agent/graph.py`:

```python
from src.tools.my_new_tool import MyNewTool

TOOLS = [
    VectorSearchTool(),
    MyNewTool(),  # Add your tool
    # ... other tools
]
```

### 4. Test

```bash
# Run the agent with a query that should trigger your tool
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "trigger my new tool"}'
```

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=src

# Run specific test file
pytest tests/test_tools.py

# Run in watch mode (for TDD)
pytest-watch
```

## Configuration

All config in `.env` file:

```bash
# Required
ANTHROPIC_API_KEY=sk-ant-...
DATABASE_URL=postgresql+asyncpg://...
QDRANT_URL=http://localhost:6333

# Optional
LOG_LEVEL=INFO          # DEBUG, INFO, WARNING, ERROR
MAX_ITERATIONS=10       # Max agent steps
CORS_ORIGINS=*          # Or specific domain
```

## Database Setup

### PostgreSQL

```sql
-- Create database
CREATE DATABASE erleah;

-- Tables created automatically by SQLAlchemy
-- See src/db/postgres.py for schema
```

### Qdrant Collections

```python
# Collections created automatically on first use
# See src/db/qdrant.py for configuration

# Collections:
# - attendees (1536-dim vectors)
# - sessions (1536-dim vectors)
# - exhibitors (1536-dim vectors)
```

## Deployment

### Docker

```bash
# Build image
docker build -t erleah-backend .

# Run
docker run -p 8000:8000 --env-file .env erleah-backend
```

### Docker Compose (Full Stack)

```bash
# Start everything
docker-compose up -d

# View logs
docker-compose logs -f api

# Stop
docker-compose down
```

## Monitoring

### Logs

```bash
# View real-time logs
docker-compose logs -f api

# Or if running locally
tail -f logs/app.log
```

### Metrics

Server exposes metrics at `/metrics` (Prometheus format).

## Troubleshooting

### "No module named 'src'"

Make sure you installed the package:
```bash
pip install -e .
```

### "Connection refused" to Qdrant/PostgreSQL

Start databases:
```bash
docker-compose up -d
```

### "Rate limit exceeded" from Anthropic

Check your API key and usage:
```bash
# View current usage
curl https://api.anthropic.com/v1/usage \
  -H "x-api-key: $ANTHROPIC_API_KEY"
```

### Agent not using a tool

Tool description might not be clear enough. Update the description in the tool class to be more explicit about when to use it.

## Performance Optimization

### Enable Prompt Caching

Already enabled by default. Conference data is cached with `cache_control: ephemeral`.

This reduces:
- **Costs by 90%** (cached input is 10x cheaper)
- **Latency by 90%** (cached tokens process instantly)

### Redis Caching

Add Redis caching for frequently accessed data:

```python
from src.db.redis import cache

@cache(ttl=3600)  # Cache for 1 hour
async def expensive_operation():
    ...
```

## Contributing

1. Create a feature branch
2. Use Cline to implement features (follow `.clinerules`)
3. Write tests
4. Submit PR

## Resources

- [LangGraph Docs](https://langchain-ai.github.io/langgraph/)
- [Anthropic Claude API](https://docs.anthropic.com/)
- [FastAPI Docs](https://fastapi.tiangolo.com/)
- [Qdrant Docs](https://qdrant.tech/documentation/)

## License

MIT

---

**Built with ❤️ using LangGraph + Claude**
