# TASK-03: Conversation Context System
## Anonymous Users with Conversation Memory

**Priority:** 🔴 Critical  
**Effort:** 1 day  
**Dependencies:** TASK-01 (graceful failure)  

---

## Goal

Replace the profile-based context system with a **conversation-first** approach. Users are anonymous — no login, no stored profiles. The conversation history IS the context. Each message sent to the backend includes the conversation ID, and the backend fetches recent messages to give the LLM conversational awareness.

This also means we can **skip the `update_profile` node entirely** and simplify the pipeline.

---

## Scope Changes

### Remove for Now
- `update_profile` node — skip entirely via conditional edge (always go to `generate_acknowledgment`)
- Profile update detection logic
- Profile fetching from Directus user records

### Keep
- `fetch_data` node — but it now fetches **conversation history** instead of profile
- Conversation history as the primary context for planning and response generation

### Add
- Conversation history caching in Redis
- Conversation summary for long conversations (token management)
- Conversation context injection into planner and response prompts

---

## Architecture

### Data Flow

```
Frontend sends: { conversation_id, message_id, conference_id }
                          │
                          ▼
                   fetch_data node
                          │
                  ┌───────┴────────┐
                  │                │
           Fetch history     Fetch conference
           from Directus     metadata (cached)
                  │                │
                  ▼                ▼
           Format as           Static context
           conversation        for prompts
           context
                  │
                  ▼
          Cache in Redis
          (TTL: 5 min)
```

### Conversation Context Object

```python
# src/agent/state.py — update AssistantState

class ConversationContext(TypedDict, total=False):
    """Context derived from conversation history."""
    conversation_id: str
    message_count: int
    recent_messages: list[dict]          # Last N messages (role + text)
    mentioned_topics: list[str]          # Extracted from history (optional, LLM-derived)
    referenced_entities: list[str]       # Entity IDs mentioned in past responses
    summary: str | None                  # Compressed summary for long conversations
    is_first_message: bool
```

Update `AssistantState`:
```python
class AssistantState(TypedDict):
    # ... existing fields ...
    conversation_context: Optional[ConversationContext]
    
    # These become optional/unused:
    # user_profile: Optional[dict]         # Not used for anonymous
    # profile_needs_update: bool           # Always False
```

---

## Implementation

### 1. Simplify the Pipeline

In `graph.py`, make `should_update_profile` always skip:

```python
def should_update_profile(state: AssistantState) -> str:
    """Skip profile updates — anonymous users only."""
    # Always skip to acknowledgment for anonymous mode
    return "generate_acknowledgment"
```

Or cleaner: remove the conditional edge entirely and wire `fetch_data` → `generate_acknowledgment` directly. Keep the `update_profile` node code in the codebase but unwired, so it's easy to re-enable later.

### 2. Conversation History Fetcher

```python
# src/services/conversation.py

import structlog
from src.services.directus import DirectusClient
from src.services.cache import CacheService

logger = structlog.get_logger()

MAX_HISTORY_MESSAGES = 20    # Max messages to fetch
CONTEXT_WINDOW_MESSAGES = 10 # Messages to include in LLM context
SUMMARY_THRESHOLD = 15       # Summarize if more than this many messages


class ConversationService:
    """Fetch and manage conversation context."""
    
    def __init__(self, directus: DirectusClient, cache: CacheService):
        self.directus = directus
        self.cache = cache
    
    async def get_context(self, conversation_id: str) -> dict:
        """
        Get conversation context, using cache if available.
        
        Returns ConversationContext dict.
        """
        cache_key = f"conv:{conversation_id}"
        
        # Try cache first
        cached = await self.cache.get(cache_key, cache_type="conversation")
        if cached:
            logger.info("conversation_cache_hit", conversation_id=conversation_id)
            return cached
        
        # Fetch from Directus
        messages = await self.directus.get_conversation_messages(
            conversation_id=conversation_id,
            limit=MAX_HISTORY_MESSAGES,
            sort="-date_created",  # Newest first
        )
        
        # Reverse to chronological order
        messages = list(reversed(messages))
        
        # Build context
        context = {
            "conversation_id": conversation_id,
            "message_count": len(messages),
            "is_first_message": len(messages) <= 1,
            "recent_messages": self._format_messages(messages[-CONTEXT_WINDOW_MESSAGES:]),
            "referenced_entities": self._extract_referenced_ids(messages),
            "summary": None,
        }
        
        # Cache it (short TTL since new messages come in)
        await self.cache.set(cache_key, context, ttl=120)  # 2 min TTL
        
        logger.info(
            "conversation_context_built",
            conversation_id=conversation_id,
            message_count=len(messages),
            cached=True,
        )
        
        return context
    
    def _format_messages(self, messages: list[dict]) -> list[dict]:
        """Format raw Directus messages for LLM context."""
        formatted = []
        for msg in messages:
            formatted.append({
                "role": msg.get("role", "user"),
                "text": msg.get("messageText", ""),
                "timestamp": msg.get("date_created", ""),
            })
        return formatted
    
    def _extract_referenced_ids(self, messages: list[dict]) -> list[str]:
        """Extract entity IDs from past assistant responses (for card rendering)."""
        ids = []
        for msg in messages:
            if msg.get("role") == "assistant":
                metadata = msg.get("metadata") or {}
                ids.extend(metadata.get("referenced_ids", []))
        return list(set(ids))  # Deduplicate
    
    async def invalidate(self, conversation_id: str):
        """Invalidate cache when a new message is added."""
        cache_key = f"conv:{conversation_id}"
        await self.cache.delete(cache_key)
```

### 3. Conversation Summary for Long Chats

When conversations exceed `SUMMARY_THRESHOLD` messages, compress older messages into a summary to save tokens:

```python
# src/services/conversation.py (continued)

async def get_context_with_summary(
    self, conversation_id: str, llm_client
) -> dict:
    """
    Get context, compressing old messages into a summary if needed.
    
    Strategy:
    - Last 10 messages: included verbatim
    - Messages 11-20: summarized into 2-3 sentences
    - Messages 20+: dropped (summary covers them)
    """
    context = await self.get_context(conversation_id)
    
    if context["message_count"] <= SUMMARY_THRESHOLD:
        return context
    
    # Check if we already have a cached summary
    summary_key = f"conv_summary:{conversation_id}:{context['message_count']}"
    cached_summary = await self.cache.get(summary_key)
    
    if cached_summary:
        context["summary"] = cached_summary
        return context
    
    # Generate summary of older messages
    older_messages = context["recent_messages"][:-CONTEXT_WINDOW_MESSAGES]
    if older_messages:
        summary = await self._summarize_messages(older_messages, llm_client)
        context["summary"] = summary
        
        # Cache the summary (longer TTL since old messages don't change)
        await self.cache.set(summary_key, summary, ttl=600)  # 10 min
    
    # Trim to just the recent messages
    context["recent_messages"] = context["recent_messages"][-CONTEXT_WINDOW_MESSAGES:]
    
    return context

async def _summarize_messages(self, messages: list[dict], llm_client) -> str:
    """Use a fast model to summarize older conversation messages."""
    messages_text = "\n".join(
        f"{m['role']}: {m['text']}" for m in messages
    )
    
    response = await llm_client.quick_completion(
        system="Summarize this conversation history in 2-3 sentences. Focus on what the user asked about and what was recommended.",
        user=messages_text,
        max_tokens=150,
    )
    return response
```

### 4. Inject Context Into Prompts

Update the planner and response generator prompts to use conversation context:

```python
# In plan_queries prompt building

def build_planner_context(state: AssistantState) -> str:
    """Build the dynamic context for the planner."""
    ctx = state.get("conversation_context", {})
    
    parts = []
    
    if ctx.get("summary"):
        parts.append(f"Conversation summary: {ctx['summary']}")
    
    if ctx.get("recent_messages"):
        parts.append("Recent conversation:")
        for msg in ctx["recent_messages"][-5:]:  # Last 5 for planner
            parts.append(f"  {msg['role']}: {msg['text'][:200]}")
    
    if ctx.get("is_first_message"):
        parts.append("This is the user's first message in this conversation.")
    
    if ctx.get("referenced_entities"):
        parts.append(f"Previously mentioned entities: {', '.join(ctx['referenced_entities'][:10])}")
    
    return "\n".join(parts)
```

### 5. Update fetch_data Node

```python
# src/agent/nodes/fetch_data.py — simplified for anonymous users

@graceful_node("fetch_data", critical=False)
async def fetch_data_parallel(state: AssistantState) -> dict:
    """Fetch conversation context and conference data in parallel."""
    
    conversation_service = get_conversation_service()
    
    # Parallel fetch: conversation history + conference metadata
    conv_context, conference_data = await asyncio.gather(
        conversation_service.get_context(state["conversation_id"]),
        get_conference_metadata(state["conference_id"]),  # Cached
        return_exceptions=True,
    )
    
    # Handle individual failures gracefully
    if isinstance(conv_context, Exception):
        logger.error("conversation_fetch_failed", error=str(conv_context))
        conv_context = {
            "conversation_id": state["conversation_id"],
            "message_count": 0,
            "is_first_message": True,
            "recent_messages": [],
            "referenced_entities": [],
            "summary": None,
        }
    
    return {
        "conversation_context": conv_context,
        "conference_data": conference_data if not isinstance(conference_data, Exception) else {},
        "profile_needs_update": False,  # Always False for anonymous
    }
```

### 6. Cache Invalidation on New Message

When a new message comes in, invalidate the conversation cache so the next request gets fresh history:

```python
# In the /api/chat endpoint, after receiving the request

await conversation_service.invalidate(request.conversation_id)
```

---

## Token Budget

Conversation context consumes LLM tokens. Here's the budget:

| Component | Est. Tokens | Notes |
|-----------|-------------|-------|
| Conversation summary | ~100 | For conversations > 15 messages |
| Recent messages (10) | ~500-1000 | Depends on message length |
| Referenced entities | ~50 | Just IDs |
| Total context overhead | ~650-1150 | Per request |

This is well within budget, especially with Anthropic prompt caching on the static portions.

---

## Testing

```python
async def test_first_message_context():
    """First message should have is_first_message=True."""
    service = ConversationService(mock_directus_empty, mock_cache)
    ctx = await service.get_context("conv-1")
    assert ctx["is_first_message"] is True
    assert ctx["recent_messages"] == []

async def test_conversation_context_caching():
    """Second call should hit cache."""
    service = ConversationService(mock_directus, mock_cache)
    await service.get_context("conv-1")
    await service.get_context("conv-1")
    assert mock_directus.get_conversation_messages.call_count == 1  # Only called once

async def test_cache_invalidation():
    """New message should invalidate cache."""
    service = ConversationService(mock_directus, mock_cache)
    await service.get_context("conv-1")
    await service.invalidate("conv-1")
    await service.get_context("conv-1")
    assert mock_directus.get_conversation_messages.call_count == 2  # Called twice

async def test_long_conversation_summary():
    """Conversations over threshold should get summarized."""
    mock_directus = create_mock_with_n_messages(20)
    service = ConversationService(mock_directus, mock_cache)
    ctx = await service.get_context_with_summary("conv-1", mock_llm)
    assert ctx["summary"] is not None
    assert len(ctx["recent_messages"]) == CONTEXT_WINDOW_MESSAGES
```

---

## Acceptance Criteria

- [ ] `update_profile` node is bypassed (conditional always skips it)
- [ ] `fetch_data` fetches conversation history instead of user profile
- [ ] `ConversationService` with Redis caching (2 min TTL)
- [ ] Cache invalidation when new messages arrive
- [ ] Conversation context injected into planner and response prompts
- [ ] Long conversation summary generation (> 15 messages)
- [ ] `is_first_message` flag for first-time greeting behavior
- [ ] `referenced_entities` extraction from past responses
- [ ] Graceful fallback if conversation fetch fails (empty context, not crash)
- [ ] Unit tests for caching, invalidation, and summary generation
