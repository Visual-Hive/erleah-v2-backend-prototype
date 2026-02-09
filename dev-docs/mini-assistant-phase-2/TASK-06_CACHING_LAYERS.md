# TASK-06: Caching Layers
## Embedding Cache + Query Result Cache

**Priority:** 🟡 Important  
**Effort:** 1-2 days  
**Dependencies:** TASK-04 (real Qdrant/Directus connected), TASK-05 (Redis confirmed working)  

---

## Goal

Add two caching layers that reduce latency and cost:

1. **Embedding Cache** — avoid re-embedding the same query text (saves ~200ms + OpenAI cost per cached hit)
2. **Query Result Cache** — avoid re-running identical Qdrant searches (saves ~500-1500ms per cached hit)

These sit on top of the already-implemented Redis infrastructure and the Anthropic prompt caching (which is already working).

---

## Layer 1: Embedding Cache

### Why
The same query text (or very similar) gets embedded repeatedly:
- User asks "AI sessions" → embed "AI sessions"
- Different user asks "AI sessions" → embed again (wasted)
- Planner generates similar queries across conversations

OpenAI embedding costs are low (~$0.0001/query) but the **200-300ms latency per embed call** adds up, especially when the planner generates 3-5 queries per request.

### Implementation

```python
# src/services/embedding.py — add caching layer

import hashlib
import json
import structlog
from src.services.cache import get_cache_service

logger = structlog.get_logger()

EMBEDDING_CACHE_TTL = 3600  # 1 hour — embeddings don't change


async def get_embedding_cached(text: str) -> list[float]:
    """
    Get embedding with Redis cache.
    
    Cache key: md5 of normalized text.
    ~200ms savings per cache hit.
    """
    cache = get_cache_service()
    
    # Normalize text for consistent cache keys
    normalized = text.strip().lower()
    cache_key = f"embed:{hashlib.md5(normalized.encode()).hexdigest()}"
    
    # Try cache
    cached = await cache.get(cache_key, cache_type="embedding")
    if cached:
        return cached
    
    # Cache miss — call OpenAI
    embedding = await get_embedding(text)
    
    # Cache it
    await cache.set(cache_key, embedding, ttl=EMBEDDING_CACHE_TTL)
    
    return embedding


async def get_embeddings_batch_cached(texts: list[str]) -> list[list[float]]:
    """
    Batch embedding with per-text cache checks.
    
    Strategy:
    1. Check cache for each text
    2. Batch-embed only the cache misses
    3. Cache the new embeddings
    4. Return all in original order
    """
    cache = get_cache_service()
    
    results: list[list[float] | None] = [None] * len(texts)
    uncached_indices: list[int] = []
    uncached_texts: list[str] = []
    
    # Check cache for each text
    for i, text in enumerate(texts):
        normalized = text.strip().lower()
        cache_key = f"embed:{hashlib.md5(normalized.encode()).hexdigest()}"
        
        cached = await cache.get(cache_key, cache_type="embedding")
        if cached:
            results[i] = cached
        else:
            uncached_indices.append(i)
            uncached_texts.append(text)
    
    logger.info(
        "embedding_batch_cache",
        total=len(texts),
        cached=len(texts) - len(uncached_texts),
        uncached=len(uncached_texts),
    )
    
    # Batch embed uncached texts
    if uncached_texts:
        new_embeddings = await get_embeddings_batch(uncached_texts)
        
        for idx, embedding in zip(uncached_indices, new_embeddings):
            results[idx] = embedding
            
            # Cache the new embedding
            text = texts[idx]
            normalized = text.strip().lower()
            cache_key = f"embed:{hashlib.md5(normalized.encode()).hexdigest()}"
            await cache.set(cache_key, embedding, ttl=EMBEDDING_CACHE_TTL)
    
    return results
```

### Wire Into Search

Update `QdrantService.search()` to use cached embeddings:

```python
# In src/services/qdrant_service.py

async def search(self, collection, query_text, ...):
    # Use cached embedding instead of raw embedding
    query_vector = await get_embedding_cached(query_text)
    # ... rest of search logic ...
```

---

## Layer 2: Query Result Cache

### Why
Identical queries happen often:
- Multiple users asking about "AI sessions" at a conference
- Same user retrying after a timeout
- Similar queries generating the same planner output

Caching the full Qdrant search result saves 500-1500ms per hit and reduces load on Qdrant.

### Cache Key Design

The cache key must be **deterministic** for identical queries:

```python
# Key components:
# - collection name
# - query text (normalized)
# - conference_id
# - filters (sorted, serialized)
# - limit
# - score_threshold

# Example key:
# query:sessions:a1b2c3:conf-123:limit10:thresh0.3
```

### Implementation

```python
# src/services/query_cache.py

import hashlib
import json
import structlog
from src.services.cache import get_cache_service

logger = structlog.get_logger()

QUERY_CACHE_TTL = 300  # 5 minutes — conference data changes infrequently


def build_query_cache_key(
    collection: str,
    query_text: str,
    conference_id: str,
    filters: dict | None = None,
    limit: int = 10,
    score_threshold: float = 0.3,
) -> str:
    """Build a deterministic cache key for a query."""
    normalized_query = query_text.strip().lower()
    
    # Sort filters for deterministic key
    filter_str = json.dumps(filters or {}, sort_keys=True)
    
    raw = f"{collection}:{normalized_query}:{conference_id}:{filter_str}:{limit}:{score_threshold}"
    key_hash = hashlib.md5(raw.encode()).hexdigest()[:12]
    
    return f"query:{collection}:{key_hash}"


async def get_cached_query(
    collection: str,
    query_text: str,
    conference_id: str,
    filters: dict | None = None,
    limit: int = 10,
    score_threshold: float = 0.3,
) -> list[dict] | None:
    """Check cache for query results."""
    cache = get_cache_service()
    key = build_query_cache_key(collection, query_text, conference_id, filters, limit, score_threshold)
    
    result = await cache.get(key, cache_type="query")
    if result:
        logger.info("query_cache_hit", collection=collection, query=query_text[:30])
    return result


async def cache_query_results(
    collection: str,
    query_text: str,
    conference_id: str,
    results: list[dict],
    filters: dict | None = None,
    limit: int = 10,
    score_threshold: float = 0.3,
) -> None:
    """Cache query results."""
    cache = get_cache_service()
    key = build_query_cache_key(collection, query_text, conference_id, filters, limit, score_threshold)
    
    await cache.set(key, results, ttl=QUERY_CACHE_TTL)
    logger.info("query_cached", collection=collection, query=query_text[:30], results=len(results))
```

### Wire Into QdrantService

```python
# src/services/qdrant_service.py — add caching

async def search(self, collection, query_text, conference_id, limit=10, score_threshold=0.3, filters=None):
    """Semantic search with result caching."""
    
    # Check cache first
    cached = await get_cached_query(
        collection, query_text, conference_id, filters, limit, score_threshold
    )
    if cached is not None:
        return cached
    
    # Cache miss — do the actual search
    query_vector = await get_embedding_cached(query_text)  # Also cached!
    
    # ... Qdrant search logic ...
    
    results = [...]
    
    # Cache the results
    await cache_query_results(
        collection, query_text, conference_id, results, filters, limit, score_threshold
    )
    
    return results
```

---

## Layer 3: Conference Metadata Cache (Bonus, Quick Win)

Conference metadata (name, dates, venue) almost never changes. Cache it aggressively:

```python
# In DirectusClient or a ConferenceService

CONFERENCE_CACHE_TTL = 1800  # 30 minutes

async def get_conference_cached(self, conference_id: str) -> dict | None:
    cache = get_cache_service()
    cache_key = f"conference:{conference_id}"
    
    cached = await cache.get(cache_key, cache_type="conference")
    if cached:
        return cached
    
    conference = await self.get_conference(conference_id)
    if conference:
        await cache.set(cache_key, conference, ttl=CONFERENCE_CACHE_TTL)
    
    return conference
```

---

## Cache Invalidation Strategy

| Cache Type | TTL | Invalidation Trigger |
|------------|-----|---------------------|
| Embedding | 1 hour | Never (embeddings don't change) |
| Query results | 5 min | Auto-expire; or invalidate if conference data is updated |
| Conference metadata | 30 min | Auto-expire; or invalidate on admin update |
| Conversation context | 2 min | Invalidated on new message (TASK-03) |

For the MVP, **TTL-based expiry is sufficient**. Event-based invalidation can come later if needed.

---

## Monitoring

### Metrics to Add

```python
# These should already exist in src/monitoring/metrics.py from earlier work
# Verify they're being recorded:

CACHE_HIT = Counter("cache_hits_total", "Cache hits", ["cache_type"])
CACHE_MISS = Counter("cache_misses_total", "Cache misses", ["cache_type"])
```

### Expected Hit Rates

| Cache Type | Expected Hit Rate | Why |
|------------|-------------------|-----|
| Embedding | 40-60% | Many similar queries across users |
| Query results | 30-50% | Depends on query diversity |
| Conference metadata | 95%+ | Rarely changes, frequently accessed |

### Grafana Dashboard Query

```promql
# Cache hit rate by type
rate(cache_hits_total{cache_type="embedding"}[5m]) / 
(rate(cache_hits_total{cache_type="embedding"}[5m]) + rate(cache_misses_total{cache_type="embedding"}[5m]))
```

---

## Memory Budget

Estimate Redis memory usage:

| Cache Type | Est. Items | Size/Item | Total |
|------------|-----------|-----------|-------|
| Embeddings | 500 unique queries | ~12KB (1536 floats) | ~6MB |
| Query results | 200 unique queries | ~5KB (10 results) | ~1MB |
| Conference metadata | 5 conferences | ~2KB | ~10KB |
| Conversation context | 100 active convos | ~3KB | ~300KB |
| **Total** | | | **~7.3MB** |

Well within a typical Redis 256MB-1GB allocation.

---

## Testing

```python
def test_embedding_cache_key_normalization():
    """Same text with different casing should have same cache key."""
    key1 = build_embedding_cache_key("AI Sessions")
    key2 = build_embedding_cache_key("ai sessions")
    key3 = build_embedding_cache_key("  AI Sessions  ")
    assert key1 == key2 == key3

async def test_embedding_cache_hit():
    """Second call should use cache, not OpenAI."""
    await get_embedding_cached("test query")
    await get_embedding_cached("test query")
    assert mock_openai.embeddings.create.call_count == 1

async def test_query_cache_hit():
    """Same query should be served from cache."""
    results = await qdrant.search("sessions", "AI", "conf-1")
    cached_results = await qdrant.search("sessions", "AI", "conf-1")
    assert results == cached_results
    assert mock_qdrant_client.search.call_count == 1

async def test_query_cache_different_filters():
    """Different filters should be different cache keys."""
    key1 = build_query_cache_key("sessions", "AI", "conf-1", filters={"hall": "A"})
    key2 = build_query_cache_key("sessions", "AI", "conf-1", filters={"hall": "B"})
    assert key1 != key2

async def test_batch_embedding_partial_cache():
    """Batch embed should only call OpenAI for uncached texts."""
    # Pre-cache one embedding
    await get_embedding_cached("query 1")
    
    # Batch with mix of cached and uncached
    results = await get_embeddings_batch_cached(["query 1", "query 2", "query 3"])
    
    assert len(results) == 3
    # OpenAI should only be called for "query 2" and "query 3"
    assert mock_openai.embeddings.create.call_count == 2  # 1 initial + 1 batch of 2
```

---

## Acceptance Criteria

- [ ] Embedding cache: Redis-backed, 1hr TTL, normalized text keys
- [ ] Batch embedding: only embeds cache-misses, caches new results
- [ ] Query result cache: Redis-backed, 5min TTL, deterministic keys
- [ ] Conference metadata cache: Redis-backed, 30min TTL
- [ ] `QdrantService.search()` checks cache before searching
- [ ] Cache metrics recorded (hits/misses by type)
- [ ] Memory usage within budget (~10MB total)
- [ ] All caches fail gracefully (cache down = bypass, not crash)
- [ ] Unit tests for key generation, cache hits, partial batch caching
- [ ] Cache hit rates visible in Prometheus metrics
