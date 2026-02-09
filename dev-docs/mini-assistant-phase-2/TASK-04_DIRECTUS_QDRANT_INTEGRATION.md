# TASK-04: Real Directus + Qdrant Integration
## Wire Up the Playground

**Priority:** 🔴 Critical  
**Effort:** 2-3 days  
**Dependencies:** TASK-01 (graceful failure), TASK-02 (Directus streaming), TASK-03 (conversation context)  

---

## Goal

Connect the pipeline to real Directus and Qdrant instances using the playground environment. This is where the backend goes from "demo mode" to actually searching real conference data and writing real messages.

**Prerequisites:**
- Playground `.env` added to the repo with Directus URL, API key, Qdrant URL, conference ID
- Existing Qdrant collections with embedded conference data (sessions, exhibitors, attendees)

---

## Part A: Directus Client

### What It Needs to Do

| Operation | Used By | Priority |
|-----------|---------|----------|
| Get conversation messages | `fetch_data` (TASK-03) | 🔴 Must |
| Create assistant message | `DirectusMessageWriter` (TASK-02) | 🔴 Must |
| Update message text + status | `DirectusMessageWriter` (TASK-02) | 🔴 Must |
| Get conference metadata | `fetch_data` | 🟡 Should |
| Validate conversation exists | Chat endpoint | 🟡 Should |

### Implementation

```python
# src/services/directus.py

import httpx
import structlog
from src.config import settings

logger = structlog.get_logger()


class DirectusClient:
    """Async Directus REST API client."""
    
    def __init__(self):
        self.base_url = settings.directus_url.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {settings.directus_api_key}",
            "Content-Type": "application/json",
        }
        self.client: httpx.AsyncClient | None = None
    
    async def connect(self):
        """Initialize the HTTP client."""
        self.client = httpx.AsyncClient(
            base_url=self.base_url,
            headers=self.headers,
            timeout=httpx.Timeout(10.0, connect=5.0),
        )
        logger.info("directus_connected", url=self.base_url)
    
    async def close(self):
        """Close the HTTP client."""
        if self.client:
            await self.client.aclose()
    
    # --- Conversations ---
    
    async def get_conversation(self, conversation_id: str) -> dict | None:
        """Fetch a conversation by ID."""
        resp = await self.client.get(f"/items/conversations/{conversation_id}")
        resp.raise_for_status()
        return resp.json().get("data")
    
    async def get_conversation_messages(
        self,
        conversation_id: str,
        limit: int = 20,
        sort: str = "-date_created",
    ) -> list[dict]:
        """Fetch messages for a conversation."""
        resp = await self.client.get(
            "/items/messages",
            params={
                "filter[conversation_id][_eq]": conversation_id,
                "limit": limit,
                "sort": sort,
                "fields": "id,role,messageText,status,metadata,date_created",
            },
        )
        resp.raise_for_status()
        return resp.json().get("data", [])
    
    # --- Messages ---
    
    async def create_message(
        self,
        conversation_id: str,
        role: str,
        message_text: str,
        status: str = "completed",
        metadata: dict | None = None,
    ) -> dict:
        """Create a new message in a conversation."""
        payload = {
            "conversation_id": conversation_id,
            "role": role,
            "messageText": message_text,
            "status": status,
        }
        if metadata:
            payload["metadata"] = metadata
        
        resp = await self.client.post("/items/messages", json=payload)
        resp.raise_for_status()
        return resp.json().get("data")
    
    async def update_message(self, message_id: str, data: dict) -> dict:
        """Update a message (used for streaming chunks and completion)."""
        resp = await self.client.patch(f"/items/messages/{message_id}", json=data)
        resp.raise_for_status()
        return resp.json().get("data")
    
    # --- Conference ---
    
    async def get_conference(self, conference_id: str) -> dict | None:
        """Fetch conference metadata."""
        resp = await self.client.get(
            f"/items/conferences/{conference_id}",
            params={
                "fields": "id,name,description,start_date,end_date,venue,timezone",
            },
        )
        resp.raise_for_status()
        return resp.json().get("data")
    
    # --- Health ---
    
    async def health_check(self) -> bool:
        """Check if Directus is reachable."""
        try:
            resp = await self.client.get("/server/ping")
            return resp.status_code == 200
        except Exception:
            return False
```

### Field Mapping Validation

Before going live, verify these field names match the actual Directus schema:

```python
# Checklist — update these if your Directus collection names differ:
CONVERSATIONS_COLLECTION = "conversations"  # or "Conversations"?
MESSAGES_COLLECTION = "messages"            # or "Messages"?

# Message fields — verify against Directus:
# - messageText (camelCase? or message_text?)
# - conversation_id (or conversation?)
# - role (user/assistant)
# - status (pending/streaming/completed)
# - metadata (JSON field?)
# - date_created (auto?)
```

> **Action item:** When the `.env` is configured, run a quick test script that fetches one conversation and one message, and print the raw JSON to confirm field names.

---

## Part B: Qdrant Integration

### What It Needs to Do

| Operation | Used By | Priority |
|-----------|---------|----------|
| Semantic search (single vector) | `execute_queries` | 🔴 Must |
| Multi-faceted search | `execute_queries` (profile mode) | 🟡 Later |
| Health check | TASK-05 health endpoint | 🟡 Should |

### Implementation

```python
# src/services/qdrant_service.py

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Filter, FieldCondition, MatchValue
import structlog
from src.config import settings
from src.services.embedding import get_embedding

logger = structlog.get_logger()


class QdrantService:
    """Async Qdrant vector search client."""
    
    def __init__(self):
        self.client: AsyncQdrantClient | None = None
    
    async def connect(self):
        """Initialize Qdrant client."""
        self.client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
            timeout=10.0,
        )
        logger.info("qdrant_connected", url=settings.qdrant_url)
    
    async def close(self):
        """Close the client."""
        if self.client:
            await self.client.close()
    
    async def search(
        self,
        collection: str,
        query_text: str,
        conference_id: str,
        limit: int = 10,
        score_threshold: float = 0.3,
        filters: dict | None = None,
    ) -> list[dict]:
        """
        Semantic search against a Qdrant collection.
        
        1. Embed the query text
        2. Search with optional filters
        3. Return scored results
        """
        # Embed query
        query_vector = await get_embedding(query_text)
        
        # Build filter
        must_conditions = [
            FieldCondition(
                key="conference_id",
                match=MatchValue(value=conference_id),
            )
        ]
        
        if filters:
            for key, value in filters.items():
                must_conditions.append(
                    FieldCondition(key=key, match=MatchValue(value=value))
                )
        
        qdrant_filter = Filter(must=must_conditions)
        
        # Search
        results = await self.client.search(
            collection_name=collection,
            query_vector=query_vector,
            query_filter=qdrant_filter,
            limit=limit,
            score_threshold=score_threshold,
        )
        
        # Format results
        formatted = []
        for point in results:
            formatted.append({
                "id": point.id,
                "score": point.score,
                "payload": point.payload,
            })
        
        logger.info(
            "qdrant_search_complete",
            collection=collection,
            query=query_text[:50],
            results=len(formatted),
            top_score=formatted[0]["score"] if formatted else 0,
        )
        
        return formatted
    
    async def health_check(self) -> bool:
        """Check if Qdrant is reachable."""
        try:
            collections = await self.client.get_collections()
            return True
        except Exception:
            return False
```

### Collection Discovery

Before wiring up search, discover what collections exist and their schemas:

```python
# One-time discovery script — run against playground

async def discover_collections():
    """Print all Qdrant collections and their schemas."""
    client = AsyncQdrantClient(url=settings.qdrant_url)
    
    collections = await client.get_collections()
    
    for col in collections.collections:
        info = await client.get_collection(col.name)
        print(f"\n=== {col.name} ===")
        print(f"  Points: {info.points_count}")
        print(f"  Vector size: {info.config.params.vectors}")
        
        # Sample a point to see payload structure
        points = await client.scroll(
            collection_name=col.name,
            limit=1,
        )
        if points[0]:
            print(f"  Sample payload keys: {list(points[0][0].payload.keys())}")
    
    await client.close()
```

> **Action item:** Run this against the playground Qdrant to confirm collection names, vector dimensions, and payload structure. The collection names and payload fields drive the `execute_queries` node.

---

## Part C: Embedding Service

```python
# src/services/embedding.py

import openai
import structlog
from src.config import settings

logger = structlog.get_logger()

_client = None


def get_openai_client():
    global _client
    if _client is None:
        _client = openai.AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


async def get_embedding(text: str) -> list[float]:
    """Get embedding for a single text using OpenAI."""
    client = get_openai_client()
    
    response = await client.embeddings.create(
        model=settings.embedding_model,  # text-embedding-3-small
        input=text,
    )
    
    return response.data[0].embedding


async def get_embeddings_batch(texts: list[str]) -> list[list[float]]:
    """Get embeddings for multiple texts in a single API call."""
    if not texts:
        return []
    
    client = get_openai_client()
    
    response = await client.embeddings.create(
        model=settings.embedding_model,
        input=texts,
    )
    
    # Return in same order as input
    return [item.embedding for item in sorted(response.data, key=lambda x: x.index)]
```

---

## Part D: Wire execute_queries to Real Qdrant

The `execute_queries` node currently needs to translate planner output into real Qdrant searches.

### Query Mapping

The planner outputs queries like:
```json
{
  "table": "sessions",
  "query_text": "AI and machine learning sessions",
  "search_mode": "semantic",
  "limit": 10,
  "score_threshold": 0.3,
  "filters": {}
}
```

Map `table` to Qdrant collection names:

```python
# src/search/collection_map.py

# Map planner table names to actual Qdrant collection names
# UPDATE THESE after running the discovery script
COLLECTION_MAP = {
    "sessions": "conference_sessions",         # Adjust to actual name
    "exhibitors": "conference_exhibitors",     # Adjust to actual name
    "attendees": "conference_attendees",       # Adjust to actual name
    "speakers": "conference_speakers",         # Adjust to actual name
}
```

### Update execute_queries Node

```python
# In src/agent/nodes/execute_queries.py — replace mock search with real search

async def _execute_single_query(query: dict, qdrant: QdrantService, conference_id: str) -> tuple[str, list]:
    """Execute a single query against Qdrant."""
    table = query.get("table", "sessions")
    collection = COLLECTION_MAP.get(table, table)
    query_text = query.get("query_text", "")
    limit = query.get("limit", 10)
    score_threshold = query.get("score_threshold", 0.3)
    
    results = await qdrant.search(
        collection=collection,
        query_text=query_text,
        conference_id=conference_id,
        limit=limit,
        score_threshold=score_threshold,
    )
    
    return table, results
```

---

## Part E: Integration Test Script

Create a quick test you can run after setting up the `.env`:

```python
# scripts/test_integration.py

"""
Quick integration test against playground.
Run: python -m scripts.test_integration
"""

import asyncio
from src.config import settings
from src.services.directus import DirectusClient
from src.services.qdrant_service import QdrantService
from src.services.embedding import get_embedding


async def main():
    print("=== Integration Test ===\n")
    
    # 1. Test Directus
    print("1. Testing Directus...")
    directus = DirectusClient()
    await directus.connect()
    
    healthy = await directus.health_check()
    print(f"   Health: {'✅' if healthy else '❌'}")
    
    conference = await directus.get_conference(settings.default_conference_id)
    print(f"   Conference: {conference.get('name', 'NOT FOUND') if conference else '❌ NOT FOUND'}")
    
    await directus.close()
    
    # 2. Test Qdrant
    print("\n2. Testing Qdrant...")
    qdrant = QdrantService()
    await qdrant.connect()
    
    healthy = await qdrant.health_check()
    print(f"   Health: {'✅' if healthy else '❌'}")
    
    # Discover collections
    collections = await qdrant.client.get_collections()
    for col in collections.collections:
        info = await qdrant.client.get_collection(col.name)
        print(f"   Collection: {col.name} ({info.points_count} points)")
    
    await qdrant.close()
    
    # 3. Test Embedding
    print("\n3. Testing Embeddings...")
    embedding = await get_embedding("test query about AI sessions")
    print(f"   Embedding dims: {len(embedding)} ({'✅' if len(embedding) == 1536 else '⚠️ unexpected'})")
    
    # 4. Test End-to-End Search
    print("\n4. Testing End-to-End Search...")
    qdrant = QdrantService()
    await qdrant.connect()
    
    # Try searching each collection
    for table, collection in COLLECTION_MAP.items():
        try:
            results = await qdrant.search(
                collection=collection,
                query_text="technology and innovation",
                conference_id=settings.default_conference_id,
                limit=3,
            )
            print(f"   {table}: {len(results)} results (top score: {results[0]['score']:.3f})" if results else f"   {table}: 0 results")
        except Exception as e:
            print(f"   {table}: ❌ {e}")
    
    await qdrant.close()
    
    print("\n=== Done ===")


if __name__ == "__main__":
    asyncio.run(main())
```

---

## Testing

```python
async def test_directus_create_and_update_message():
    """Test the full message lifecycle against real Directus."""
    # Create, update, complete — verify each state
    
async def test_qdrant_search_returns_results():
    """Test that a broad query returns results from each collection."""
    
async def test_full_pipeline_with_real_services():
    """Send a real message through the pipeline and verify response."""
```

---

## Acceptance Criteria

- [ ] `DirectusClient` connects and authenticates with playground Directus
- [ ] Can fetch conversations and messages from Directus
- [ ] Can create and update messages in Directus (for streaming fallback)
- [ ] `QdrantService` connects to playground Qdrant
- [ ] Collection names mapped correctly to planner output
- [ ] Semantic search returns scored results from real collections
- [ ] Embedding service works with OpenAI text-embedding-3-small
- [ ] `execute_queries` node uses real Qdrant instead of mocks
- [ ] Integration test script passes against playground
- [ ] End-to-end: send a message via devtools → get a real response with real search results
- [ ] All service failures handled gracefully (TASK-01 error wrapper)
