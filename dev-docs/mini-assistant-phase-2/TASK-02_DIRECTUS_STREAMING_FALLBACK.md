# TASK-02: Directus Streaming Fallback
## Keep the Frontend Working Without SSE

**Priority:** 🔴 Critical  
**Effort:** 1 day  
**Dependencies:** TASK-01 (graceful failure system)  

---

## Goal

The current frontend uses **Directus WebSocket subscriptions** to watch for message updates. It doesn't speak SSE. Rather than rewriting the frontend, add a "Directus streaming mode" to the backend that writes response chunks directly to the Directus message record — exactly like n8n does today.

This means:
- Backend creates an assistant message in Directus with `status: "streaming"`
- As chunks arrive from the LLM, backend updates `messageText` on that record
- Frontend sees updates via its existing Directus WebSocket subscription
- When complete, backend sets `status: "completed"`

The SSE stream remains active for the devtools GUI. Both systems work simultaneously.

---

## Architecture

### Dual Output Mode

```
LangGraph Pipeline
       │
       ├──→ SSE Stream (devtools GUI, debug events)     ← existing, keep as-is
       │
       └──→ Directus Message Updates (frontend)          ← NEW fallback
             │
             ├─ Create message (status: "streaming")
             ├─ Update messageText with each chunk
             ├─ Update messageText with acknowledgment
             ├─ Update messageText with progress messages
             └─ Set status: "completed" with final text
```

### Configuration

```python
# src/config.py

class Settings(BaseSettings):
    # ... existing ...
    
    # Streaming mode
    directus_streaming_enabled: bool = True     # Write chunks to Directus messages
    directus_streaming_interval_ms: int = 200   # Min ms between Directus updates (debounce)
    sse_streaming_enabled: bool = True           # SSE for devtools (always on in dev)
```

Both can be on simultaneously. In production, `directus_streaming_enabled=True`. In dev, both are on.

---

## Implementation

### 1. Directus Message Writer

```python
# src/services/directus_streaming.py

import asyncio
import time
import structlog

logger = structlog.get_logger()


class DirectusMessageWriter:
    """
    Writes streaming response chunks to a Directus message record.
    
    Debounces updates to avoid hammering Directus with too many PATCH requests.
    The frontend watches for changes via Directus WebSocket.
    """
    
    def __init__(self, directus_client, message_id: str, debounce_ms: int = 200):
        self.client = directus_client
        self.message_id = message_id
        self.debounce_ms = debounce_ms
        self.buffer = ""
        self.last_flush_time = 0
        self.flush_task: asyncio.Task | None = None
        self.is_closed = False
    
    async def create_message(self, conversation_id: str, conference_id: str) -> str:
        """Create the assistant message record in Directus. Returns message ID."""
        message = await self.client.create_message(
            conversation_id=conversation_id,
            role="assistant",
            message_text="",
            status="streaming",
            metadata={"source": "python-backend"},
        )
        self.message_id = message["id"]
        logger.info("directus_message_created", message_id=self.message_id)
        return self.message_id
    
    async def write_acknowledgment(self, text: str):
        """Write the acknowledgment as the initial message text."""
        self.buffer = text
        await self._flush_now()
    
    async def write_chunk(self, chunk: str):
        """Buffer a response chunk and debounce the Directus update."""
        if self.is_closed:
            return
        
        self.buffer += chunk
        
        now = time.time() * 1000
        elapsed = now - self.last_flush_time
        
        if elapsed >= self.debounce_ms:
            await self._flush_now()
        else:
            # Schedule a flush after the debounce period
            if self.flush_task is None or self.flush_task.done():
                remaining = self.debounce_ms - elapsed
                self.flush_task = asyncio.create_task(
                    self._flush_after(remaining / 1000)
                )
    
    async def write_progress(self, message: str):
        """
        Write a progress message.
        
        Strategy: prepend progress to the buffer if no response text yet,
        or ignore if response streaming has started (progress would disrupt the text).
        """
        # Only show progress if we haven't started the actual response yet
        if not self.buffer or self.buffer == self._last_acknowledgment:
            self.buffer = message
            await self._flush_now()
    
    async def complete(self, final_text: str, metadata: dict | None = None):
        """Mark the message as completed with final text and metadata."""
        self.is_closed = True
        
        # Cancel pending flush
        if self.flush_task and not self.flush_task.done():
            self.flush_task.cancel()
        
        update_data = {
            "messageText": final_text,
            "status": "completed",
        }
        if metadata:
            update_data["metadata"] = metadata
        
        await self.client.update_message(self.message_id, update_data)
        logger.info("directus_message_completed", message_id=self.message_id)
    
    async def error(self, error_text: str):
        """Mark the message as completed with an error response."""
        self.is_closed = True
        
        if self.flush_task and not self.flush_task.done():
            self.flush_task.cancel()
        
        await self.client.update_message(self.message_id, {
            "messageText": error_text,
            "status": "completed",
            "metadata": {"error": True},
        })
        logger.info("directus_message_error", message_id=self.message_id)
    
    async def _flush_now(self):
        """Immediately update the Directus record with current buffer."""
        try:
            await self.client.update_message(self.message_id, {
                "messageText": self.buffer,
            })
            self.last_flush_time = time.time() * 1000
        except Exception as e:
            logger.error("directus_flush_failed", error=str(e), message_id=self.message_id)
    
    async def _flush_after(self, delay: float):
        """Flush after a delay (debounce)."""
        await asyncio.sleep(delay)
        await self._flush_now()
```

### 2. Hook Into the Pipeline

Modify `stream_agent_response()` in `graph.py` to optionally write to Directus alongside SSE:

```python
# In stream_agent_response() — alongside existing SSE yields

async def stream_agent_response(state, debug=False, directus_writer=None):
    """
    Stream the pipeline, yielding SSE events AND optionally writing to Directus.
    """
    
    # ... existing SSE streaming logic ...
    
    async for event in graph.astream_events(state, version="v2"):
        
        # Existing: yield SSE events
        if event_is_chunk:
            yield {"event": "chunk", "data": {"text": chunk_text}}
            
            # NEW: also write to Directus if enabled
            if directus_writer:
                await directus_writer.write_chunk(chunk_text)
        
        elif event_is_acknowledgment:
            yield {"event": "acknowledgment", "data": {"text": ack_text}}
            
            if directus_writer:
                await directus_writer.write_acknowledgment(ack_text)
        
        elif event_is_progress:
            yield {"event": "progress", "data": {"node": node, "message": msg}}
            
            if directus_writer:
                await directus_writer.write_progress(msg)
    
    # Finalize
    if directus_writer:
        await directus_writer.complete(
            final_text=full_response_text,
            metadata={
                "trace_id": state["trace_id"],
                "referenced_ids": state.get("referenced_ids", []),
                "quality_score": state.get("quality_score"),
            },
        )
```

### 3. Chat Endpoint Integration

```python
# In the /api/chat endpoint

@router.post("/api/chat")
async def chat(request: ChatRequest):
    # ... existing validation ...
    
    directus_writer = None
    
    if settings.directus_streaming_enabled:
        directus_writer = DirectusMessageWriter(
            directus_client=get_directus_client(),
            message_id="",  # Will be set after creation
            debounce_ms=settings.directus_streaming_interval_ms,
        )
        # Create the assistant message in Directus
        assistant_message_id = await directus_writer.create_message(
            conversation_id=request.conversation_id,
            conference_id=request.conference_id,
        )
    
    # Stream the pipeline
    async for sse_event in stream_agent_response(
        state=initial_state,
        debug=settings.debug_mode,
        directus_writer=directus_writer,
    ):
        yield format_sse(sse_event)
    
    # Return the message ID so the frontend knows which message to watch
    yield format_sse({
        "event": "done",
        "data": {
            "assistant_message_id": assistant_message_id,
            "trace_id": state["trace_id"],
        },
    })
```

### 4. Error Integration (from TASK-01)

If the pipeline fails, the `DirectusMessageWriter` must still complete the message:

```python
try:
    async for sse_event in stream_agent_response(...):
        yield format_sse(sse_event)
except Exception as e:
    error_text = get_user_error(e)  # From TASK-01's fallback system
    if directus_writer:
        await directus_writer.error(error_text)
    yield format_sse({"event": "error", "data": {"message": error_text}})
```

---

## Debounce Tuning

The debounce interval controls how often we PATCH the Directus record:

| Interval | Directus PATCH/sec | UX Feel | Recommendation |
|----------|-------------------|---------|----------------|
| 50ms | 20/sec | Very smooth, high load | Too aggressive |
| 100ms | 10/sec | Smooth | Good for low-traffic |
| 200ms | 5/sec | Slightly chunky | **Good default** |
| 500ms | 2/sec | Noticeably batched | Fallback for high load |

Start with **200ms**. If Directus shows strain, increase to 500ms. The frontend's WebSocket subscription has its own latency (~50-100ms) so sub-100ms debounce is wasted effort.

---

## Migration Path

```
Now:     Backend → SSE → DevTools GUI only
         (frontend not connected)

TASK-02: Backend → SSE → DevTools GUI
         Backend → Directus PATCH → WebSocket → Frontend  ← new
         (both work simultaneously)

Later:   Backend → SSE → Frontend (when SSE is implemented)
         Backend → Directus PATCH → disabled
         (flip the config flag)
```

---

## Testing

```python
async def test_directus_writer_debounce():
    """Verify chunks are debounced, not sent 1:1."""
    mock_client = AsyncMock()
    writer = DirectusMessageWriter(mock_client, "msg-1", debounce_ms=200)
    
    # Write 10 chunks rapidly
    for i in range(10):
        await writer.write_chunk(f"chunk{i} ")
        await asyncio.sleep(0.01)  # 10ms between chunks
    
    await asyncio.sleep(0.3)  # Let debounce flush
    
    # Should have far fewer than 10 PATCH calls
    assert mock_client.update_message.call_count < 5

async def test_directus_writer_complete():
    """Verify complete() writes final text and status."""
    mock_client = AsyncMock()
    writer = DirectusMessageWriter(mock_client, "msg-1")
    
    await writer.write_chunk("Hello ")
    await writer.write_chunk("world")
    await writer.complete("Hello world", metadata={"trace_id": "t1"})
    
    final_call = mock_client.update_message.call_args
    assert final_call[0][1]["status"] == "completed"
    assert final_call[0][1]["messageText"] == "Hello world"

async def test_directus_writer_error():
    """Verify error() still completes the message."""
    mock_client = AsyncMock()
    writer = DirectusMessageWriter(mock_client, "msg-1")
    
    await writer.error("Something went wrong, please try again.")
    
    final_call = mock_client.update_message.call_args
    assert final_call[0][1]["status"] == "completed"
    assert "went wrong" in final_call[0][1]["messageText"]
```

---

## Acceptance Criteria

- [ ] `DirectusMessageWriter` class created with debounced PATCH updates
- [ ] `stream_agent_response()` accepts optional `directus_writer` parameter
- [ ] Acknowledgment, progress, and response chunks all write to Directus
- [ ] Message created with `status: "streaming"`, completed with `status: "completed"`
- [ ] Error responses still complete the Directus message (never leaves it in "streaming")
- [ ] Debounce interval is configurable via settings
- [ ] Feature toggle: `directus_streaming_enabled` in config
- [ ] SSE stream continues to work for devtools regardless of this setting
- [ ] Metadata (trace_id, referenced_ids, quality_score) saved on completion
- [ ] Unit tests for debounce behavior, completion, and error handling
