# Mini-Assistant Developer Guide
## Implementation Details for Python Developer

This guide provides detailed implementation instructions for building the Erleah Mini-Assistant backend. Read this alongside the [MINI_ASSISTANT_ROADMAP.md](./MINI_ASSISTANT_ROADMAP.md).

---

## Table of Contents

1. [Project Setup](#1-project-setup)
2. [Directus Integration](#2-directus-integration)
3. [Qdrant & Multi-Faceted Search](#3-qdrant--multi-faceted-search)
4. [LangGraph Agent](#4-langgraph-agent)
5. [Tools Implementation](#5-tools-implementation)
6. [API Layer](#6-api-layer)
7. [Streaming (DIY Approach)](#7-streaming-diy-approach)
8. [Testing](#8-testing)
9. [Deployment](#9-deployment)

---

## 1. Project Setup

### Dependencies

Create `pyproject.toml`:

```toml
[tool.poetry]
name = "erleah-mini-assistant"
version = "0.1.0"
description = "Mini-Assistant backend for Erleah conference platform"
authors = ["Your Name <you@example.com>"]

[tool.poetry.dependencies]
python = "^3.11"

# Web Framework
fastapi = "^0.109.0"
uvicorn = {extras = ["standard"], version = "^0.27.0"}
pydantic = "^2.5.0"
pydantic-settings = "^2.1.0"

# Async HTTP
httpx = "^0.26.0"
aiohttp = "^3.9.0"

# LLM & Agent
langgraph = "^0.0.40"
langchain-core = "^0.1.20"
langchain-anthropic = "^0.1.1"
anthropic = "^0.18.0"

# Vector Database
qdrant-client = "^1.7.0"

# Embeddings
openai = "^1.10.0"

# Caching
redis = "^5.0.0"

# Logging & Monitoring
structlog = "^24.1.0"
sentry-sdk = {extras = ["fastapi"], version = "^1.39.0"}

[tool.poetry.group.dev.dependencies]
pytest = "^7.4.0"
pytest-asyncio = "^0.23.0"
pytest-cov = "^4.1.0"
httpx = "^0.26.0"
ruff = "^0.1.0"
mypy = "^1.8.0"

[build-system]
requires = ["poetry-core"]
build-backend = "poetry.core.masonry.api"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

### Environment Variables

Create `.env.example`:

```bash
# ============================================
# ERLEAH MINI-ASSISTANT CONFIGURATION
# ============================================

# Environment
ENVIRONMENT=development  # development | staging | production

# API Configuration
API_HOST=0.0.0.0
API_PORT=8000
API_DEBUG=true

# Directus
DIRECTUS_URL=https://your-directus-instance.com
DIRECTUS_API_KEY=your-directus-api-key

# Qdrant
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=  # Optional for local dev

# Anthropic (Claude)
ANTHROPIC_API_KEY=your-anthropic-api-key
ANTHROPIC_MODEL=claude-sonnet-4-20250514

# OpenAI (Embeddings)
OPENAI_API_KEY=your-openai-api-key
EMBEDDING_MODEL=text-embedding-3-small

# Redis (Caching)
REDIS_URL=redis://localhost:6379/0

# Logging
LOG_LEVEL=INFO
LOG_FORMAT=json  # json | console

# Sentry (Error Tracking)
SENTRY_DSN=  # Optional, leave empty for local dev

# Conference (can be overridden per request)
DEFAULT_CONFERENCE_ID=your-conference-uuid
```

### Configuration Module

Create `src/config/settings.py`:

```python
"""Application configuration using Pydantic Settings."""

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Environment
    environment: Literal["development", "staging", "production"] = "development"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_debug: bool = False

    # Directus
    directus_url: str
    directus_api_key: str

    # Qdrant
    qdrant_url: str = "http://localhost:6333"
    qdrant_api_key: str | None = None

    # Anthropic
    anthropic_api_key: str
    anthropic_model: str = "claude-sonnet-4-20250514"

    # OpenAI (Embeddings)
    openai_api_key: str
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # Logging
    log_level: str = "INFO"
    log_format: Literal["json", "console"] = "json"

    # Sentry
    sentry_dsn: str | None = None

    # Conference
    default_conference_id: str | None = None

    @field_validator("directus_url", "qdrant_url")
    @classmethod
    def remove_trailing_slash(cls, v: str) -> str:
        return v.rstrip("/")

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
```

### Docker Compose (Local Development)

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  # Erleah Mini-Assistant API
  api:
    build:
      context: .
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    environment:
      - ENVIRONMENT=development
      - QDRANT_URL=http://qdrant:6333
      - REDIS_URL=redis://redis:6379/0
    env_file:
      - .env
    volumes:
      - ./src:/app/src  # Hot reload
    depends_on:
      - qdrant
      - redis
    command: uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload

  # Qdrant Vector Database
  qdrant:
    image: qdrant/qdrant:v1.7.4
    ports:
      - "6333:6333"
      - "6334:6334"  # gRPC
    volumes:
      - qdrant_data:/qdrant/storage
    environment:
      - QDRANT__SERVICE__GRPC_PORT=6334

  # Redis Cache
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
    command: redis-server --appendonly yes

volumes:
  qdrant_data:
  redis_data:
```

### Basic FastAPI Application

Create `src/api/main.py`:

```python
"""FastAPI application entry point."""

import structlog
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from src.config.settings import get_settings
from src.api.routes import chat, health
from src.utils.logging import setup_logging

settings = get_settings()
logger = structlog.get_logger()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    setup_logging(settings.log_level, settings.log_format)
    logger.info("Starting Erleah Mini-Assistant", environment=settings.environment)
    
    # Initialize services (Qdrant, Redis, etc.)
    # These will be added in later phases
    
    yield
    
    # Shutdown
    logger.info("Shutting down Erleah Mini-Assistant")


app = FastAPI(
    title="Erleah Mini-Assistant API",
    description="AI-powered conference assistant for sessions, exhibitors, and speakers",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS (adjust origins for production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.api_debug else ["https://your-frontend.com"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Routes
app.include_router(health.router, tags=["Health"])
app.include_router(chat.router, prefix="/api", tags=["Chat"])
```

Create `src/api/routes/health.py`:

```python
"""Health check endpoint."""

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health_check():
    """Basic health check."""
    return {
        "status": "healthy",
        "service": "erleah-mini-assistant",
    }


@router.get("/health/ready")
async def readiness_check():
    """
    Readiness check - verifies all dependencies are available.
    Add checks for Directus, Qdrant, Redis as they're implemented.
    """
    # TODO: Add dependency checks
    return {
        "status": "ready",
        "checks": {
            "directus": "ok",
            "qdrant": "ok",
            "redis": "ok",
        }
    }
```

---

## 2. Directus Integration

### Directus Client Service

Create `src/services/directus.py`:

```python
"""Directus API client for data access and message streaming."""

import httpx
import structlog
from typing import Any

from src.config.settings import get_settings

settings = get_settings()
logger = structlog.get_logger()


class DirectusClient:
    """Async client for Directus API operations."""

    def __init__(self):
        self.base_url = settings.directus_url
        self.headers = {
            "Authorization": f"Bearer {settings.directus_api_key}",
            "Content-Type": "application/json",
        }
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                headers=self.headers,
                timeout=30.0,
            )
        return self._client

    async def close(self):
        """Close the HTTP client."""
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    # =========================================
    # CONVERSATION OPERATIONS
    # =========================================

    async def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """
        Fetch conversation with its messages.
        
        Args:
            conversation_id: UUID of the conversation
            
        Returns:
            Conversation dict with messages, or None if not found
        """
        client = await self._get_client()
        
        try:
            response = await client.get(
                f"/items/conversations/{conversation_id}",
                params={
                    "fields": "*,messages.*",
                }
            )
            response.raise_for_status()
            data = response.json()
            return data.get("data")
            
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            logger.error("Failed to fetch conversation", 
                        conversation_id=conversation_id, 
                        error=str(e))
            raise

    async def get_conversation_messages(
        self, 
        conversation_id: str, 
        limit: int = 10
    ) -> list[dict[str, Any]]:
        """
        Fetch recent messages from a conversation.
        
        Args:
            conversation_id: UUID of the conversation
            limit: Maximum messages to return
            
        Returns:
            List of message dicts, newest first
        """
        client = await self._get_client()
        
        response = await client.get(
            "/items/messages",
            params={
                "filter[conversation_id][_eq]": conversation_id,
                "sort": "-date_created",
                "limit": limit,
                "fields": "id,role,messageText,date_created,status",
            }
        )
        response.raise_for_status()
        data = response.json()
        
        # Return in chronological order (oldest first)
        messages = data.get("data", [])
        return list(reversed(messages))

    # =========================================
    # MESSAGE OPERATIONS (DIY Streaming)
    # =========================================

    async def create_message(
        self,
        conversation_id: str,
        role: str = "assistant",
        message_text: str = "",
        status: str = "streaming",
    ) -> dict[str, Any]:
        """
        Create a new message in a conversation.
        
        Args:
            conversation_id: UUID of the conversation
            role: "user" or "assistant"
            message_text: Initial message content
            status: "streaming" or "completed"
            
        Returns:
            Created message dict with ID
        """
        client = await self._get_client()
        
        response = await client.post(
            "/items/messages",
            json={
                "conversation_id": conversation_id,
                "role": role,
                "messageText": message_text,
                "status": status,
                "user_created": "public-user",  # Public User ID
            }
        )
        response.raise_for_status()
        data = response.json()
        
        logger.debug("Created message", 
                    message_id=data["data"]["id"],
                    conversation_id=conversation_id)
        
        return data["data"]

    async def update_message_text(
        self, 
        message_id: str, 
        text: str,
        status: str | None = None,
    ) -> None:
        """
        Update message text (used for streaming chunks).
        
        Args:
            message_id: UUID of the message
            text: New message text (replaces existing)
            status: Optional status update
        """
        client = await self._get_client()
        
        payload = {"messageText": text}
        if status:
            payload["status"] = status
        
        response = await client.patch(
            f"/items/messages/{message_id}",
            json=payload
        )
        response.raise_for_status()

    async def complete_message(
        self,
        message_id: str,
        final_text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """
        Mark message as completed with final text.
        
        Args:
            message_id: UUID of the message
            final_text: Final message content
            metadata: Optional metadata (tool usage, etc.)
        """
        client = await self._get_client()
        
        payload = {
            "messageText": final_text,
            "status": "completed",
        }
        if metadata:
            payload["metadata"] = metadata
        
        response = await client.patch(
            f"/items/messages/{message_id}",
            json=payload
        )
        response.raise_for_status()
        
        logger.debug("Completed message", message_id=message_id)

    # =========================================
    # CONFERENCE DATA
    # =========================================

    async def get_conference(self, conference_id: str) -> dict[str, Any] | None:
        """Fetch conference details."""
        client = await self._get_client()
        
        try:
            response = await client.get(f"/items/conferences/{conference_id}")
            response.raise_for_status()
            return response.json().get("data")
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return None
            raise

    async def get_sessions(
        self, 
        conference_id: str,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Fetch all sessions for a conference."""
        client = await self._get_client()
        
        response = await client.get(
            "/items/sessions",
            params={
                "filter[conference_id][_eq]": conference_id,
                "limit": limit,
                "fields": "*,speakers.*",
            }
        )
        response.raise_for_status()
        return response.json().get("data", [])

    async def get_exhibitors(
        self, 
        conference_id: str,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Fetch all exhibitors for a conference."""
        client = await self._get_client()
        
        response = await client.get(
            "/items/exhibitors",
            params={
                "filter[conference_id][_eq]": conference_id,
                "limit": limit,
                "fields": "*",
            }
        )
        response.raise_for_status()
        return response.json().get("data", [])

    async def get_speakers(
        self, 
        conference_id: str,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Fetch all speakers for a conference."""
        client = await self._get_client()
        
        response = await client.get(
            "/items/speakers",
            params={
                "filter[conference_id][_eq]": conference_id,
                "limit": limit,
                "fields": "*,sessions.*",
            }
        )
        response.raise_for_status()
        return response.json().get("data", [])


# Singleton instance
_directus_client: DirectusClient | None = None


def get_directus_client() -> DirectusClient:
    """Get singleton Directus client."""
    global _directus_client
    if _directus_client is None:
        _directus_client = DirectusClient()
    return _directus_client
```

---

## 3. Qdrant & Multi-Faceted Search

### Understanding Multi-Faceted Search

**The Problem:** Traditional vector search can be thrown off by rare words.

**The Solution:** Split each entity into multiple "facets" - each facet captures one semantic dimension.

**Example for Exhibitor "TechCorp":**

```
Master Record (1 vector):
"TechCorp is a leading AI solutions provider specializing in machine learning 
infrastructure. We help enterprises deploy ML models at scale. Our products 
include MLOps platform, model serving infrastructure, and AI monitoring tools."

Faceted Records (6 vectors):
1. what_we_sell: "We sell MLOps platforms, model serving infrastructure, AI 
   monitoring and observability tools for machine learning systems."
   
2. problems_we_solve: "We help companies deploy ML models faster, monitor AI 
   systems in production, reduce ML infrastructure costs, and scale ML operations."
   
3. who_we_help: "We work with enterprise companies, data science teams, ML 
   engineers, and DevOps teams building AI-powered products."
   
4. our_expertise: "We are experts in machine learning operations, Kubernetes, 
   model deployment, AI infrastructure, and MLOps best practices."
   
5. industries_we_serve: "We serve fintech, healthcare, e-commerce, and 
   enterprise software companies using AI."
   
6. why_visit_us: "Visit our booth to see live demos of our MLOps platform, 
   talk to our ML engineers, and get a free infrastructure assessment."
```

**How Search Works:**

1. **Specific Query** ("Find AI monitoring companies") → Search `exhibitors_master`
2. **Vague Query** ("Who can help me with ML deployment?") → Search `exhibitors_facets` with facet pairs

### Qdrant Client Service

Create `src/services/qdrant.py`:

```python
"""Qdrant vector database client."""

import structlog
from qdrant_client import QdrantClient, AsyncQdrantClient
from qdrant_client.http import models
from qdrant_client.http.models import Distance, VectorParams, PointStruct

from src.config.settings import get_settings

settings = get_settings()
logger = structlog.get_logger()

# Collection names
COLLECTIONS = {
    "sessions_master": "sessions_master",
    "sessions_facets": "sessions_facets",
    "exhibitors_master": "exhibitors_master",
    "exhibitors_facets": "exhibitors_facets",
    "speakers_master": "speakers_master",
    "speakers_facets": "speakers_facets",
}


class QdrantService:
    """Service for Qdrant vector operations."""

    def __init__(self):
        self.client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key,
            timeout=30,
        )
        self.vector_size = settings.embedding_dimensions

    async def ensure_collections(self) -> None:
        """Create all collections if they don't exist."""
        for collection_name in COLLECTIONS.values():
            try:
                await self.client.get_collection(collection_name)
                logger.debug(f"Collection {collection_name} exists")
            except Exception:
                await self.client.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=self.vector_size,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info(f"Created collection: {collection_name}")

    async def upsert_points(
        self,
        collection_name: str,
        points: list[PointStruct],
    ) -> None:
        """Insert or update points in a collection."""
        await self.client.upsert(
            collection_name=collection_name,
            points=points,
        )
        logger.debug(f"Upserted {len(points)} points to {collection_name}")

    async def search(
        self,
        collection_name: str,
        query_vector: list[float],
        conference_id: str,
        limit: int = 10,
        score_threshold: float = 0.5,
        filter_conditions: dict | None = None,
    ) -> list[models.ScoredPoint]:
        """
        Search a collection with filters.
        
        Args:
            collection_name: Name of the collection to search
            query_vector: Query embedding vector
            conference_id: Filter by conference
            limit: Max results to return
            score_threshold: Minimum similarity score
            filter_conditions: Additional filter conditions
            
        Returns:
            List of scored points
        """
        # Build filter
        must_conditions = [
            models.FieldCondition(
                key="conference_id",
                match=models.MatchValue(value=conference_id),
            )
        ]
        
        if filter_conditions:
            for key, value in filter_conditions.items():
                must_conditions.append(
                    models.FieldCondition(
                        key=key,
                        match=models.MatchValue(value=value),
                    )
                )
        
        query_filter = models.Filter(must=must_conditions)
        
        results = await self.client.search(
            collection_name=collection_name,
            query_vector=query_vector,
            query_filter=query_filter,
            limit=limit,
            score_threshold=score_threshold,
        )
        
        return results

    async def search_faceted(
        self,
        entity_type: str,  # "sessions", "exhibitors", "speakers"
        query_vector: list[float],
        conference_id: str,
        facet_key: str | None = None,
        limit: int = 10,
    ) -> list[models.ScoredPoint]:
        """
        Search faceted collection, optionally filtering by facet key.
        
        Args:
            entity_type: Type of entity to search
            query_vector: Query embedding
            conference_id: Filter by conference
            facet_key: Optional specific facet to search
            limit: Max results
            
        Returns:
            List of scored points from faceted collection
        """
        collection_name = f"{entity_type}_facets"
        
        filter_conditions = {}
        if facet_key:
            filter_conditions["facet_key"] = facet_key
        
        return await self.search(
            collection_name=collection_name,
            query_vector=query_vector,
            conference_id=conference_id,
            limit=limit,
            filter_conditions=filter_conditions if filter_conditions else None,
        )

    async def close(self):
        """Close the client connection."""
        await self.client.close()


# Singleton
_qdrant_service: QdrantService | None = None


def get_qdrant_service() -> QdrantService:
    """Get singleton Qdrant service."""
    global _qdrant_service
    if _qdrant_service is None:
        _qdrant_service = QdrantService()
    return _qdrant_service
```

### Multi-Faceted Search Logic

Create `src/search/faceted.py`:

```python
"""Multi-faceted search implementation - THE SECRET SAUCE."""

import asyncio
import structlog
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from src.services.qdrant import get_qdrant_service
from src.services.embedding import get_embedding_service

logger = structlog.get_logger()

EntityType = Literal["sessions", "exhibitors", "speakers"]


@dataclass
class FacetedSearchResult:
    """Result from faceted search with aggregated scoring."""
    entity_id: str
    entity_type: EntityType
    total_score: float
    facet_matches: int
    facet_scores: dict[str, float]
    payload: dict


async def faceted_search(
    entity_type: EntityType,
    query: str,
    conference_id: str,
    limit: int = 10,
) -> list[FacetedSearchResult]:
    """
    Perform multi-faceted search across all facets of an entity type.
    
    This is the "secret sauce" - instead of searching one big vector,
    we search multiple facets and aggregate the scores.
    
    Args:
        entity_type: "sessions", "exhibitors", or "speakers"
        query: Natural language search query
        conference_id: Conference to search within
        limit: Maximum results to return
        
    Returns:
        List of aggregated results, sorted by composite score
    """
    qdrant = get_qdrant_service()
    embedding_service = get_embedding_service()
    
    # Get query embedding
    query_vector = await embedding_service.embed_text(query)
    
    # Search all facets in parallel
    # We search the faceted collection without specifying a facet_key
    # to get matches across ALL facets
    facet_results = await qdrant.search_faceted(
        entity_type=entity_type,
        query_vector=query_vector,
        conference_id=conference_id,
        facet_key=None,  # Search all facets
        limit=limit * 5,  # Get more results for aggregation
    )
    
    # Aggregate results by entity_id
    entity_scores: dict[str, dict] = defaultdict(lambda: {
        "facet_scores": {},
        "payload": None,
    })
    
    for result in facet_results:
        entity_id = result.payload.get("entity_id")
        facet_key = result.payload.get("facet_key")
        
        if entity_id and facet_key:
            # Track score for this facet
            entity_scores[entity_id]["facet_scores"][facet_key] = result.score
            
            # Keep payload from first match (they should be the same)
            if entity_scores[entity_id]["payload"] is None:
                entity_scores[entity_id]["payload"] = result.payload
    
    # Calculate composite scores
    results = []
    for entity_id, data in entity_scores.items():
        facet_scores = data["facet_scores"]
        
        # Composite score formula:
        # - Higher score for more facet matches
        # - Higher score for higher individual facet scores
        num_matches = len(facet_scores)
        avg_score = sum(facet_scores.values()) / num_matches if num_matches > 0 else 0
        
        # Weighted composite: 60% average score, 40% bonus for multiple matches
        # Max facets is typically 5-6, so we normalize
        match_bonus = min(num_matches / 4, 1.0)  # Cap bonus at 4+ matches
        composite_score = (avg_score * 0.6) + (match_bonus * 0.4)
        
        results.append(FacetedSearchResult(
            entity_id=entity_id,
            entity_type=entity_type,
            total_score=composite_score,
            facet_matches=num_matches,
            facet_scores=facet_scores,
            payload=data["payload"],
        ))
    
    # Sort by composite score
    results.sort(key=lambda x: x.total_score, reverse=True)
    
    logger.debug(
        "Faceted search complete",
        entity_type=entity_type,
        query=query[:50],
        results_count=len(results),
    )
    
    return results[:limit]


async def hybrid_search(
    entity_type: EntityType,
    query: str,
    conference_id: str,
    use_faceted: bool = True,
    limit: int = 10,
) -> list[FacetedSearchResult]:
    """
    Hybrid search that chooses between master and faceted based on query type.
    
    Use master collection for specific queries (names, keywords).
    Use faceted collection for vague/recommendation queries.
    
    Args:
        entity_type: Entity type to search
        query: Search query
        conference_id: Conference ID
        use_faceted: Whether to use faceted search (True for vague queries)
        limit: Max results
        
    Returns:
        Search results
    """
    qdrant = get_qdrant_service()
    embedding_service = get_embedding_service()
    
    query_vector = await embedding_service.embed_text(query)
    
    if use_faceted:
        # Use multi-faceted search for vague queries
        return await faceted_search(
            entity_type=entity_type,
            query=query,
            conference_id=conference_id,
            limit=limit,
        )
    else:
        # Use master collection for specific queries
        collection_name = f"{entity_type}_master"
        results = await qdrant.search(
            collection_name=collection_name,
            query_vector=query_vector,
            conference_id=conference_id,
            limit=limit,
        )
        
        # Convert to FacetedSearchResult format for consistency
        return [
            FacetedSearchResult(
                entity_id=r.payload.get("entity_id", r.id),
                entity_type=entity_type,
                total_score=r.score,
                facet_matches=1,
                facet_scores={"master": r.score},
                payload=r.payload,
            )
            for r in results
        ]
```

### Embedding Service

Create `src/services/embedding.py`:

```python
"""OpenAI embedding service."""

import structlog
from openai import AsyncOpenAI

from src.config.settings import get_settings

settings = get_settings()
logger = structlog.get_logger()


class EmbeddingService:
    """Service for generating text embeddings."""

    def __init__(self):
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.embedding_model

    async def embed_text(self, text: str) -> list[float]:
        """
        Generate embedding for a single text.
        
        Args:
            text: Text to embed
            
        Returns:
            Embedding vector (1536 dimensions)
        """
        response = await self.client.embeddings.create(
            model=self.model,
            input=text,
        )
        return response.data[0].embedding

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """
        Generate embeddings for multiple texts.
        
        Args:
            texts: List of texts to embed
            
        Returns:
            List of embedding vectors
        """
        # OpenAI allows up to 2048 texts per batch
        response = await self.client.embeddings.create(
            model=self.model,
            input=texts,
        )
        return [item.embedding for item in response.data]


# Singleton
_embedding_service: EmbeddingService | None = None


def get_embedding_service() -> EmbeddingService:
    """Get singleton embedding service."""
    global _embedding_service
    if _embedding_service is None:
        _embedding_service = EmbeddingService()
    return _embedding_service
```

---

## 4. LangGraph Agent

### Agent State

Create `src/agent/state.py`:

```python
"""Agent state definition for LangGraph."""

from typing import Annotated, Literal, TypedDict
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State maintained throughout agent execution."""
    
    # Core identifiers
    conversation_id: str
    message_id: str  # Assistant message ID (for streaming)
    conference_id: str
    
    # Messages (LangGraph manages this)
    messages: Annotated[list, add_messages]
    
    # Conversation context
    conversation_history: list[dict]
    
    # Agent reasoning
    intent: str | None
    entities: dict | None
    plan: list[str] | None
    
    # Tool execution
    tool_results: list[dict]
    needs_more_info: bool
    
    # Control
    iteration: int
    max_iterations: int
    
    # Response
    response_text: str
    response_complete: bool
```

### LangGraph Definition

Create `src/agent/graph.py`:

```python
"""LangGraph agent definition."""

import structlog
from langgraph.graph import StateGraph, END

from src.agent.state import AgentState
from src.agent.nodes.understand import understand_intent
from src.agent.nodes.plan import plan_actions
from src.agent.nodes.execute import execute_tools
from src.agent.nodes.reflect import reflect_on_results
from src.agent.nodes.respond import generate_response

logger = structlog.get_logger()


def should_continue(state: AgentState) -> str:
    """
    Decide whether to continue tool execution or generate response.
    
    Returns:
        "execute" to run more tools
        "respond" to generate final response
    """
    if state.get("needs_more_info", False) and state.get("iteration", 0) < state.get("max_iterations", 5):
        return "execute"
    return "respond"


def create_agent_graph() -> StateGraph:
    """
    Create the LangGraph agent workflow.
    
    Flow:
    understand → plan → execute → reflect → (execute | respond)
                                     ↑           ↓
                                     └───────────┘
    """
    workflow = StateGraph(AgentState)
    
    # Add nodes
    workflow.add_node("understand", understand_intent)
    workflow.add_node("plan", plan_actions)
    workflow.add_node("execute", execute_tools)
    workflow.add_node("reflect", reflect_on_results)
    workflow.add_node("respond", generate_response)
    
    # Add edges
    workflow.set_entry_point("understand")
    workflow.add_edge("understand", "plan")
    workflow.add_edge("plan", "execute")
    workflow.add_edge("execute", "reflect")
    
    # Conditional edge from reflect
    workflow.add_conditional_edges(
        "reflect",
        should_continue,
        {
            "execute": "execute",
            "respond": "respond",
        }
    )
    
    workflow.add_edge("respond", END)
    
    return workflow.compile()


# Create singleton agent
_agent = None


def get_agent():
    """Get compiled agent graph."""
    global _agent
    if _agent is None:
        _agent = create_agent_graph()
    return _agent
```

### Agent Nodes

Create `src/agent/nodes/understand.py`:

```python
"""Intent understanding node."""

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage

from src.agent.state import AgentState
from src.config.settings import get_settings

settings = get_settings()
logger = structlog.get_logger()

UNDERSTAND_PROMPT = """You are analyzing a user query for a conference assistant.

Classify the intent and extract relevant entities.

Intent categories:
- session_search: Looking for sessions/talks/presentations
- exhibitor_search: Looking for exhibitors/sponsors/companies
- speaker_search: Looking for specific speakers
- general_info: General conference questions (dates, venue, logistics)
- recommendation: Wants personalized recommendations ("what's good for me")
- clarification: Unclear, needs more information

Extract entities:
- topics: Subject areas mentioned (AI, gaming, marketing, etc.)
- names: Specific names mentioned (companies, people, sessions)
- time: Time constraints (morning, Day 2, after lunch)
- location: Location constraints (Hall A, Main Stage)

Respond in this exact format:
INTENT: <intent_category>
ENTITIES:
- topics: <comma-separated list or "none">
- names: <comma-separated list or "none">
- time: <time constraint or "none">
- location: <location constraint or "none">
SEARCH_TYPE: <specific|vague>

Use "specific" for queries with clear targets (names, keywords).
Use "vague" for recommendation/browsing queries.
"""


async def understand_intent(state: AgentState) -> AgentState:
    """
    Analyze user query to understand intent and extract entities.
    """
    messages = state.get("messages", [])
    if not messages:
        return {**state, "intent": "clarification", "entities": {}}
    
    # Get the latest user message
    user_message = None
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "human":
            user_message = msg.content
            break
        elif isinstance(msg, dict) and msg.get("role") == "user":
            user_message = msg.get("content", msg.get("messageText", ""))
            break
    
    if not user_message:
        return {**state, "intent": "clarification", "entities": {}}
    
    # Use Claude to understand intent
    llm = ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        temperature=0,
    )
    
    response = await llm.ainvoke([
        SystemMessage(content=UNDERSTAND_PROMPT),
        HumanMessage(content=f"User query: {user_message}"),
    ])
    
    # Parse response
    response_text = response.content
    intent = "general_info"
    entities = {"topics": [], "names": [], "time": None, "location": None}
    search_type = "vague"
    
    for line in response_text.split("\n"):
        line = line.strip()
        if line.startswith("INTENT:"):
            intent = line.replace("INTENT:", "").strip().lower()
        elif line.startswith("- topics:"):
            topics = line.replace("- topics:", "").strip()
            if topics.lower() != "none":
                entities["topics"] = [t.strip() for t in topics.split(",")]
        elif line.startswith("- names:"):
            names = line.replace("- names:", "").strip()
            if names.lower() != "none":
                entities["names"] = [n.strip() for n in names.split(",")]
        elif line.startswith("- time:"):
            time_val = line.replace("- time:", "").strip()
            if time_val.lower() != "none":
                entities["time"] = time_val
        elif line.startswith("- location:"):
            loc_val = line.replace("- location:", "").strip()
            if loc_val.lower() != "none":
                entities["location"] = loc_val
        elif line.startswith("SEARCH_TYPE:"):
            search_type = line.replace("SEARCH_TYPE:", "").strip().lower()
    
    # Add search_type to entities for later use
    entities["search_type"] = search_type
    
    logger.info(
        "Understood intent",
        intent=intent,
        entities=entities,
        query=user_message[:50],
    )
    
    return {
        **state,
        "intent": intent,
        "entities": entities,
    }
```

Create `src/agent/nodes/plan.py`:

```python
"""Action planning node."""

import structlog
from src.agent.state import AgentState

logger = structlog.get_logger()

# Map intents to tool sequences
INTENT_TO_TOOLS = {
    "session_search": ["search_sessions"],
    "exhibitor_search": ["search_exhibitors"],
    "speaker_search": ["search_speakers"],
    "general_info": ["get_conference_info"],
    "recommendation": ["search_sessions", "search_exhibitors"],
    "clarification": [],  # No tools, ask for clarification
}


async def plan_actions(state: AgentState) -> AgentState:
    """
    Determine which tools to use based on intent.
    """
    intent = state.get("intent", "general_info")
    
    # Get tool sequence for this intent
    tools_to_use = INTENT_TO_TOOLS.get(intent, ["get_conference_info"])
    
    logger.info(
        "Planned actions",
        intent=intent,
        tools=tools_to_use,
    )
    
    return {
        **state,
        "plan": tools_to_use,
    }
```

Create `src/agent/nodes/execute.py`:

```python
"""Tool execution node."""

import structlog
from src.agent.state import AgentState
from src.tools import get_tool_registry

logger = structlog.get_logger()


async def execute_tools(state: AgentState) -> AgentState:
    """
    Execute planned tools and collect results.
    """
    plan = state.get("plan", [])
    entities = state.get("entities", {})
    conference_id = state.get("conference_id")
    iteration = state.get("iteration", 0)
    
    if not plan:
        return {
            **state,
            "tool_results": [],
            "iteration": iteration + 1,
        }
    
    # Get tool registry
    registry = get_tool_registry()
    
    # Execute each tool in the plan
    results = []
    for tool_name in plan:
        tool = registry.get(tool_name)
        if tool is None:
            logger.warning(f"Tool not found: {tool_name}")
            continue
        
        try:
            # Build tool input from entities
            tool_input = {
                "conference_id": conference_id,
                "query": _build_query_from_entities(entities),
                "use_faceted": entities.get("search_type", "vague") == "vague",
            }
            
            # Add any specific filters from entities
            if entities.get("time"):
                tool_input["time_filter"] = entities["time"]
            if entities.get("location"):
                tool_input["location_filter"] = entities["location"]
            
            # Execute tool
            result = await tool.ainvoke(tool_input)
            results.append({
                "tool": tool_name,
                "success": True,
                "data": result,
            })
            
            logger.info(
                "Tool executed",
                tool=tool_name,
                results_count=len(result.get("results", [])) if isinstance(result, dict) else 0,
            )
            
        except Exception as e:
            logger.error(f"Tool execution failed: {tool_name}", error=str(e))
            results.append({
                "tool": tool_name,
                "success": False,
                "error": str(e),
            })
    
    return {
        **state,
        "tool_results": results,
        "iteration": iteration + 1,
    }


def _build_query_from_entities(entities: dict) -> str:
    """Build a search query string from extracted entities."""
    parts = []
    
    if entities.get("topics"):
        parts.extend(entities["topics"])
    
    if entities.get("names"):
        parts.extend(entities["names"])
    
    return " ".join(parts) if parts else "general"
```

Create `src/agent/nodes/reflect.py`:

```python
"""Reflection node to check if we have enough information."""

import structlog
from src.agent.state import AgentState

logger = structlog.get_logger()


async def reflect_on_results(state: AgentState) -> AgentState:
    """
    Evaluate tool results and decide if we need more information.
    """
    tool_results = state.get("tool_results", [])
    iteration = state.get("iteration", 0)
    max_iterations = state.get("max_iterations", 5)
    
    # Check if we have results
    has_results = False
    total_results = 0
    
    for result in tool_results:
        if result.get("success") and result.get("data"):
            data = result["data"]
            if isinstance(data, dict) and data.get("results"):
                total_results += len(data["results"])
                has_results = True
            elif isinstance(data, list) and len(data) > 0:
                total_results += len(data)
                has_results = True
    
    # Decision logic
    needs_more = False
    
    # If we got zero results and haven't exhausted iterations, try again
    if not has_results and iteration < max_iterations:
        # Could modify the plan here to try different tools
        needs_more = True
        logger.info("No results found, may retry with different approach")
    
    # If we hit max iterations, stop
    if iteration >= max_iterations:
        needs_more = False
        logger.info("Max iterations reached")
    
    logger.info(
        "Reflection complete",
        has_results=has_results,
        total_results=total_results,
        needs_more=needs_more,
        iteration=iteration,
    )
    
    return {
        **state,
        "needs_more_info": needs_more,
    }
```

Create `src/agent/nodes/respond.py`:

```python
"""Response generation node with streaming to Directus."""

import structlog
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage

from src.agent.state import AgentState
from src.services.directus import get_directus_client
from src.config.settings import get_settings

settings = get_settings()
logger = structlog.get_logger()

RESPONSE_PROMPT = """You are Erleah, a friendly AI assistant for conference attendees.

Based on the search results below, provide a helpful response to the user's question.

Guidelines:
- Be concise and helpful
- Mention specific names, sessions, or companies from the results
- If no results were found, say so politely and suggest alternatives
- Use a friendly, professional tone
- Format with markdown if listing multiple items

Search Results:
{results}

User's Question: {question}

Respond naturally without mentioning "search results" or technical details."""


async def generate_response(state: AgentState) -> AgentState:
    """
    Generate final response and stream to Directus.
    """
    tool_results = state.get("tool_results", [])
    messages = state.get("messages", [])
    message_id = state.get("message_id")
    
    # Get user's question
    user_question = ""
    for msg in reversed(messages):
        if hasattr(msg, "type") and msg.type == "human":
            user_question = msg.content
            break
        elif isinstance(msg, dict) and msg.get("role") == "user":
            user_question = msg.get("content", msg.get("messageText", ""))
            break
    
    # Format results for the prompt
    formatted_results = _format_results(tool_results)
    
    # Generate response with streaming
    llm = ChatAnthropic(
        model=settings.anthropic_model,
        api_key=settings.anthropic_api_key,
        temperature=0.7,
        streaming=True,
    )
    
    prompt = RESPONSE_PROMPT.format(
        results=formatted_results,
        question=user_question,
    )
    
    # Stream response to Directus
    directus = get_directus_client()
    full_response = ""
    
    async for chunk in llm.astream([
        SystemMessage(content=prompt),
        HumanMessage(content="Please respond to the user's question."),
    ]):
        if hasattr(chunk, "content") and chunk.content:
            full_response += chunk.content
            
            # Update Directus message with accumulated response
            # This is the DIY streaming approach
            await directus.update_message_text(
                message_id=message_id,
                text=full_response,
            )
    
    # Mark message as complete
    await directus.complete_message(
        message_id=message_id,
        final_text=full_response,
        metadata={
            "tools_used": [r["tool"] for r in tool_results if r.get("success")],
            "iterations": state.get("iteration", 1),
        }
    )
    
    logger.info(
        "Response generated",
        response_length=len(full_response),
        message_id=message_id,
    )
    
    return {
        **state,
        "response_text": full_response,
        "response_complete": True,
    }


def _format_results(tool_results: list[dict]) -> str:
    """Format tool results for the response prompt."""
    if not tool_results:
        return "No search was performed."
    
    sections = []
    
    for result in tool_results:
        if not result.get("success"):
            continue
            
        tool = result["tool"]
        data = result.get("data", {})
        
        if isinstance(data, dict) and "results" in data:
            items = data["results"]
        elif isinstance(data, list):
            items = data
        else:
            continue
        
        if not items:
            sections.append(f"{tool}: No results found")
            continue
        
        # Format items
        formatted_items = []
        for item in items[:10]:  # Limit to 10 items
            if isinstance(item, dict):
                name = item.get("name", item.get("title", "Unknown"))
                desc = item.get("description", item.get("bio", ""))[:200]
                score = item.get("score", item.get("total_score", 0))
                formatted_items.append(f"- {name} (relevance: {score:.2f}): {desc}")
            else:
                formatted_items.append(f"- {item}")
        
        sections.append(f"{tool}:\n" + "\n".join(formatted_items))
    
    return "\n\n".join(sections) if sections else "No results found."
```

---

## 5. Tools Implementation

See [API_CONTRACT.md](./API_CONTRACT.md) for full tool specifications.

Create `src/tools/__init__.py`:

```python
"""Tool registry and exports."""

from src.tools.base import BaseTool
from src.tools.session_search import SessionSearchTool
from src.tools.exhibitor_search import ExhibitorSearchTool
from src.tools.speaker_search import SpeakerSearchTool
from src.tools.conference_info import ConferenceInfoTool

# Tool registry
_TOOLS: dict[str, BaseTool] = {}


def register_tools():
    """Register all available tools."""
    global _TOOLS
    _TOOLS = {
        "search_sessions": SessionSearchTool(),
        "search_exhibitors": ExhibitorSearchTool(),
        "search_speakers": SpeakerSearchTool(),
        "get_conference_info": ConferenceInfoTool(),
    }


def get_tool_registry() -> dict[str, BaseTool]:
    """Get the tool registry."""
    if not _TOOLS:
        register_tools()
    return _TOOLS
```

Create `src/tools/base.py`:

```python
"""Base tool class."""

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """Base class for all tools."""
    
    name: str
    description: str
    
    @abstractmethod
    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool asynchronously."""
        pass
```

Create `src/tools/exhibitor_search.py`:

```python
"""Exhibitor search tool with multi-faceted support."""

from typing import Any
from src.tools.base import BaseTool
from src.search.faceted import hybrid_search


class ExhibitorSearchTool(BaseTool):
    """Search exhibitors using multi-faceted vectorization."""
    
    name = "search_exhibitors"
    description = """
    Search for exhibitors at the conference.
    
    Use this when the user asks about:
    - Companies or sponsors
    - Products or services
    - Booths to visit
    - "Who is selling X?"
    - "Find companies that do Y"
    
    Input:
        query: Search query (natural language)
        conference_id: Conference to search
        use_faceted: True for vague queries, False for specific
        
    Returns:
        List of matching exhibitors with relevance scores
    """
    
    async def ainvoke(self, input: dict[str, Any]) -> dict[str, Any]:
        """Execute exhibitor search."""
        query = input.get("query", "")
        conference_id = input.get("conference_id")
        use_faceted = input.get("use_faceted", True)
        limit = input.get("limit", 10)
        
        if not conference_id:
            return {"results": [], "error": "conference_id required"}
        
        results = await hybrid_search(
            entity_type="exhibitors",
            query=query,
            conference_id=conference_id,
            use_faceted=use_faceted,
            limit=limit,
        )
        
        # Format results
        formatted = []
        for r in results:
            formatted.append({
                "id": r.entity_id,
                "name": r.payload.get("name", "Unknown"),
                "description": r.payload.get("description", ""),
                "booth_number": r.payload.get("booth_number", ""),
                "category": r.payload.get("category", ""),
                "score": r.total_score,
                "facet_matches": r.facet_matches,
            })
        
        return {"results": formatted}
```

(Similar implementations for `session_search.py` and `speaker_search.py`)

---

## 6. API Layer

### Chat Endpoint

Create `src/api/routes/chat.py`:

```python
"""Chat API endpoint."""

import structlog
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.agent.graph import get_agent
from src.agent.state import AgentState
from src.services.directus import get_directus_client

logger = structlog.get_logger()
router = APIRouter()


class ChatRequest(BaseModel):
    """Request body for chat endpoint."""
    conversation_id: str = Field(..., description="Directus conversation ID")
    message_id: str = Field(..., description="User message ID in Directus")
    conference_id: str = Field(..., description="Conference ID")


class ChatResponse(BaseModel):
    """Response from chat endpoint."""
    success: bool
    assistant_message_id: str | None = None
    error: str | None = None


@router.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    """
    Process a chat message.
    
    The frontend:
    1. Creates conversation (if new)
    2. Creates user message
    3. Calls this endpoint
    4. Listens to Directus WebSocket for message updates
    
    This endpoint:
    1. Fetches conversation context
    2. Creates assistant message (status=streaming)
    3. Runs agent (streams to Directus)
    4. Returns success status
    """
    directus = get_directus_client()
    
    try:
        # Fetch conversation with messages
        conversation = await directus.get_conversation(request.conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Get conversation history for context
        messages = await directus.get_conversation_messages(
            request.conversation_id,
            limit=10,
        )
        
        # Create assistant message (will be updated during streaming)
        assistant_message = await directus.create_message(
            conversation_id=request.conversation_id,
            role="assistant",
            message_text="",
            status="streaming",
        )
        
        # Build initial state
        initial_state: AgentState = {
            "conversation_id": request.conversation_id,
            "message_id": assistant_message["id"],
            "conference_id": request.conference_id,
            "messages": _format_messages(messages),
            "conversation_history": messages,
            "intent": None,
            "entities": None,
            "plan": None,
            "tool_results": [],
            "needs_more_info": False,
            "iteration": 0,
            "max_iterations": 5,
            "response_text": "",
            "response_complete": False,
        }
        
        # Run agent
        agent = get_agent()
        final_state = await agent.ainvoke(initial_state)
        
        logger.info(
            "Chat completed",
            conversation_id=request.conversation_id,
            assistant_message_id=assistant_message["id"],
        )
        
        return ChatResponse(
            success=True,
            assistant_message_id=assistant_message["id"],
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Chat failed", error=str(e))
        return ChatResponse(
            success=False,
            error=str(e),
        )


def _format_messages(messages: list[dict]) -> list:
    """Convert Directus messages to LangChain format."""
    from langchain_core.messages import HumanMessage, AIMessage
    
    formatted = []
    for msg in messages:
        content = msg.get("messageText", msg.get("content", ""))
        role = msg.get("role", "user")
        
        if role == "user":
            formatted.append(HumanMessage(content=content))
        elif role == "assistant":
            formatted.append(AIMessage(content=content))
    
    return formatted
```

---

## 7. Streaming (DIY Approach)

The streaming approach is already implemented in the code above:

1. **Backend creates message** with `status="streaming"`
2. **Backend updates `messageText`** with each chunk from Claude
3. **Frontend has WebSocket** to Directus that detects message updates
4. **Backend marks complete** with `status="completed"`

The key code is in `src/agent/nodes/respond.py`:

```python
async for chunk in llm.astream([...]):
    if hasattr(chunk, "content") and chunk.content:
        full_response += chunk.content
        
        # Update Directus message with accumulated response
        await directus.update_message_text(
            message_id=message_id,
            text=full_response,
        )
```

---

## 8. Testing

Create `tests/conftest.py`:

```python
"""Pytest fixtures."""

import pytest
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_directus():
    """Mock Directus client."""
    client = AsyncMock()
    client.get_conversation.return_value = {
        "id": "conv-123",
        "source": "mini",
    }
    client.get_conversation_messages.return_value = []
    client.create_message.return_value = {"id": "msg-456"}
    return client


@pytest.fixture
def mock_qdrant():
    """Mock Qdrant service."""
    service = AsyncMock()
    service.search.return_value = []
    return service
```

Create `tests/unit/test_faceted_search.py`:

```python
"""Tests for multi-faceted search."""

import pytest
from src.search.faceted import FacetedSearchResult


def test_faceted_search_result_scoring():
    """Test composite scoring calculation."""
    result = FacetedSearchResult(
        entity_id="test-123",
        entity_type="exhibitors",
        total_score=0.85,
        facet_matches=4,
        facet_scores={
            "what_we_sell": 0.92,
            "problems_we_solve": 0.88,
            "who_we_help": 0.78,
            "our_expertise": 0.82,
        },
        payload={"name": "Test Corp"},
    )
    
    assert result.total_score == 0.85
    assert result.facet_matches == 4
    assert len(result.facet_scores) == 4
```

---

## 9. Deployment

### Production Dockerfile

```dockerfile
# Build stage
FROM python:3.11-slim as builder

WORKDIR /app

# Install poetry
RUN pip install poetry

# Copy dependency files
COPY pyproject.toml poetry.lock ./

# Export requirements
RUN poetry export -f requirements.txt --output requirements.txt --without-hashes

# Production stage
FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY --from=builder /app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY src/ ./src/

# Create non-root user
RUN useradd -m appuser && chown -R appuser:appuser /app
USER appuser

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run
CMD ["uvicorn", "src.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

### Azure Container App Deployment

```bash
# Build and push image
docker build -t erleah-mini-assistant:latest .
docker tag erleah-mini-assistant:latest youracr.azurecr.io/erleah-mini-assistant:latest
docker push youracr.azurecr.io/erleah-mini-assistant:latest

# Deploy to Azure Container App
az containerapp create \
    --name erleah-mini-assistant \
    --resource-group your-rg \
    --environment your-env \
    --image youracr.azurecr.io/erleah-mini-assistant:latest \
    --target-port 8000 \
    --ingress external \
    --min-replicas 1 \
    --max-replicas 3 \
    --cpu 0.5 \
    --memory 1Gi \
    --env-vars \
        ENVIRONMENT=production \
        DIRECTUS_URL=secretref:directus-url \
        DIRECTUS_API_KEY=secretref:directus-key \
        # ... other secrets
```

---

## Next Steps

1. **Start with Phase 0** - Get the project running locally
2. **Read FACET_DEFINITIONS.md** - Understand the facet configurations
3. **Read API_CONTRACT.md** - Understand frontend expectations
4. **Ask questions** before starting if anything is unclear

Good luck! 🚀
