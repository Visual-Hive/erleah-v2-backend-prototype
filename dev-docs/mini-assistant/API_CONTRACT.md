# API Contract
## Frontend ↔ Backend Interface Specification

This document defines the exact API contract between the frontend widget and the Erleah Mini-Assistant backend.

---

## Overview

### Communication Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                        FRONTEND WIDGET                          │
│                                                                 │
│  1. User types message                                          │
│  2. Frontend creates conversation in Directus (if new)          │
│  3. Frontend creates user message in Directus                   │
│  4. Frontend calls POST /api/chat                               │
│  5. Frontend listens to Directus WebSocket for message updates  │
│  6. Frontend displays streaming response                        │
└─────────────────────────┬───────────────────────────────────────┘
                          │
                          │ HTTP POST /api/chat
                          ▼
┌─────────────────────────────────────────────────────────────────┐
│                     ERLEAH BACKEND                              │
│                                                                 │
│  1. Validates request                                           │
│  2. Fetches conversation context from Directus                  │
│  3. Creates assistant message in Directus (status=streaming)    │
│  4. Runs LangGraph agent                                        │
│  5. Updates message.messageText with each chunk                 │
│  6. Marks message complete (status=completed)                   │
│  7. Returns success status                                      │
└─────────────────────────────────────────────────────────────────┘
```

---

## Endpoints

### POST /api/chat

Process a user message and generate an AI response.

#### Request

```http
POST /api/chat
Content-Type: application/json
```

```json
{
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "message_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "conference_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `conversation_id` | UUID | Yes | Directus conversation ID (created by frontend) |
| `message_id` | UUID | Yes | User message ID in Directus (created by frontend) |
| `conference_id` | UUID | Yes | Conference to search within |

#### Response (Success)

```json
{
  "success": true,
  "assistant_message_id": "9b2e3f4d-5a6b-7c8d-9e0f-1a2b3c4d5e6f"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | Whether processing started successfully |
| `assistant_message_id` | UUID | ID of the assistant message being streamed |

#### Response (Error)

```json
{
  "success": false,
  "error": "Conversation not found"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `success` | boolean | `false` |
| `error` | string | Human-readable error message |

#### Error Codes

| HTTP Status | Error | Description |
|-------------|-------|-------------|
| 400 | Invalid request | Missing or invalid fields |
| 404 | Conversation not found | conversation_id doesn't exist |
| 404 | Conference not found | conference_id doesn't exist |
| 500 | Internal error | Server-side processing error |

---

### GET /health

Basic health check endpoint.

#### Response

```json
{
  "status": "healthy",
  "service": "erleah-mini-assistant"
}
```

---

### GET /health/ready

Readiness check that verifies all dependencies.

#### Response

```json
{
  "status": "ready",
  "checks": {
    "directus": "ok",
    "qdrant": "ok",
    "redis": "ok",
    "anthropic": "ok"
  }
}
```

---

## Directus Data Models

### Conversation

The frontend creates conversations in Directus before calling the backend.

```json
{
  "id": "550e8400-e29b-41d4-a716-446655440000",
  "user_created": "public-user",
  "date_created": "2025-01-15T10:30:00Z",
  "conference_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479",
  "source": "mini",
  "status": "active"
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Auto-generated |
| `user_created` | string | Always "public-user" for mini-assistant |
| `date_created` | datetime | Auto-generated |
| `conference_id` | UUID | Associated conference |
| `source` | string | Always "mini" for mini-assistant |
| `status` | string | "active" or "closed" |

### Message

Messages are created by both frontend (user) and backend (assistant).

```json
{
  "id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
  "user_created": "public-user",
  "date_created": "2025-01-15T10:30:05Z",
  "role": "user",
  "messageText": "What AI sessions are happening tomorrow?",
  "status": "completed",
  "metadata": null
}
```

| Field | Type | Description |
|-------|------|-------------|
| `id` | UUID | Auto-generated |
| `conversation_id` | UUID | Parent conversation |
| `user_created` | string | Always "public-user" |
| `date_created` | datetime | Auto-generated |
| `role` | string | "user" or "assistant" |
| `messageText` | string | Message content (updated during streaming) |
| `status` | string | "pending", "streaming", or "completed" |
| `metadata` | object | Optional metadata (tools used, etc.) |

---

## Frontend Implementation Guide

### 1. Creating a New Conversation

When the user starts a new chat, create a conversation in Directus:

```javascript
// Create conversation
const conversation = await directus.items('conversations').createOne({
  conference_id: CONFERENCE_ID,
  source: 'mini',
  status: 'active',
  // user_created is auto-set based on your Directus config
});

const conversationId = conversation.id;
```

### 2. Sending a Message

When the user sends a message:

```javascript
async function sendMessage(conversationId, messageText) {
  // 1. Create user message in Directus
  const userMessage = await directus.items('messages').createOne({
    conversation_id: conversationId,
    role: 'user',
    messageText: messageText,
    status: 'completed',
  });

  // 2. Call backend
  const response = await fetch('https://api.erleah.com/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      conversation_id: conversationId,
      message_id: userMessage.id,
      conference_id: CONFERENCE_ID,
    }),
  });

  const result = await response.json();
  
  if (!result.success) {
    throw new Error(result.error);
  }

  return result.assistant_message_id;
}
```

### 3. Listening for Streaming Updates

Use Directus WebSocket to detect message updates:

```javascript
// Setup WebSocket connection
const ws = new WebSocket('wss://your-directus.com/websocket');

ws.onopen = () => {
  // Authenticate
  ws.send(JSON.stringify({
    type: 'auth',
    access_token: 'your-access-token',
  }));
};

// Subscribe to message updates
function subscribeToMessage(messageId) {
  ws.send(JSON.stringify({
    type: 'subscribe',
    collection: 'messages',
    uid: messageId,  // Custom UID for this subscription
  }));
}

// Handle updates
ws.onmessage = (event) => {
  const data = JSON.parse(event.data);
  
  if (data.type === 'subscription' && data.event === 'update') {
    const message = data.data[0];  // Updated message
    
    // Update UI with new text
    displayMessage(message.messageText);
    
    // Check if complete
    if (message.status === 'completed') {
      // Done streaming
      unsubscribe(data.uid);
    }
  }
};
```

### 4. Complete Flow Example

```javascript
class MiniAssistantWidget {
  constructor(conferenceId, directusUrl, apiUrl) {
    this.conferenceId = conferenceId;
    this.directus = createDirectusClient(directusUrl);
    this.apiUrl = apiUrl;
    this.conversationId = null;
    this.ws = null;
  }

  async initialize() {
    // Create conversation
    const conv = await this.directus.items('conversations').createOne({
      conference_id: this.conferenceId,
      source: 'mini',
      status: 'active',
    });
    this.conversationId = conv.id;

    // Setup WebSocket
    this.ws = new WebSocket(`${this.directus.url}/websocket`);
    this.ws.onopen = () => this.authenticate();
    this.ws.onmessage = (e) => this.handleMessage(e);
  }

  async sendMessage(text) {
    // Show user message in UI
    this.displayUserMessage(text);

    // Create message in Directus
    const userMsg = await this.directus.items('messages').createOne({
      conversation_id: this.conversationId,
      role: 'user',
      messageText: text,
      status: 'completed',
    });

    // Show loading state
    this.showLoading();

    // Call backend
    const response = await fetch(`${this.apiUrl}/api/chat`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        conversation_id: this.conversationId,
        message_id: userMsg.id,
        conference_id: this.conferenceId,
      }),
    });

    const result = await response.json();

    if (result.success) {
      // Subscribe to assistant message updates
      this.subscribeToMessage(result.assistant_message_id);
    } else {
      this.showError(result.error);
    }
  }

  subscribeToMessage(messageId) {
    this.currentMessageId = messageId;
    this.ws.send(JSON.stringify({
      type: 'subscribe',
      collection: 'messages',
      query: { filter: { id: { _eq: messageId } } },
      uid: messageId,
    }));
  }

  handleMessage(event) {
    const data = JSON.parse(event.data);

    if (data.type === 'subscription' && data.uid === this.currentMessageId) {
      const message = data.data[0];
      
      // Update displayed text
      this.updateAssistantMessage(message.messageText);

      if (message.status === 'completed') {
        this.hideLoading();
        this.unsubscribe(this.currentMessageId);
      }
    }
  }

  // ... UI methods
}
```

---

## Backend Implementation Details

### Request Validation

```python
from pydantic import BaseModel, Field, field_validator
import uuid


class ChatRequest(BaseModel):
    """Validated chat request."""
    
    conversation_id: str = Field(..., description="Directus conversation ID")
    message_id: str = Field(..., description="User message ID")
    conference_id: str = Field(..., description="Conference ID")
    
    @field_validator('conversation_id', 'message_id', 'conference_id')
    @classmethod
    def validate_uuid(cls, v: str) -> str:
        """Ensure valid UUID format."""
        try:
            uuid.UUID(v)
            return v
        except ValueError:
            raise ValueError(f"Invalid UUID: {v}")
```

### Response Formatting

```python
from pydantic import BaseModel


class ChatResponse(BaseModel):
    """Chat endpoint response."""
    
    success: bool
    assistant_message_id: str | None = None
    error: str | None = None


# Success
return ChatResponse(
    success=True,
    assistant_message_id=message.id,
)

# Error
return ChatResponse(
    success=False,
    error="Conversation not found",
)
```

### CORS Configuration

```python
from fastapi.middleware.cors import CORSMiddleware

# For development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# For production
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://your-widget-domain.com",
        "https://client-website.com",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
)
```

---

## Error Handling

### Backend Error Responses

| Scenario | HTTP Status | Response |
|----------|-------------|----------|
| Invalid JSON | 422 | `{"detail": "Validation error..."}` |
| Missing field | 422 | `{"detail": [{"loc": ["body", "conversation_id"], "msg": "field required"}]}` |
| Conversation not found | 404 | `{"success": false, "error": "Conversation not found"}` |
| Directus connection error | 500 | `{"success": false, "error": "Database connection failed"}` |
| LLM API error | 500 | `{"success": false, "error": "AI service temporarily unavailable"}` |

### Frontend Error Handling

```javascript
async function sendMessageWithRetry(text, maxRetries = 3) {
  for (let attempt = 1; attempt <= maxRetries; attempt++) {
    try {
      await sendMessage(text);
      return;
    } catch (error) {
      if (attempt === maxRetries) {
        showError("Sorry, something went wrong. Please try again.");
        return;
      }
      
      // Exponential backoff
      await sleep(1000 * Math.pow(2, attempt));
    }
  }
}
```

---

## Rate Limiting

### Limits

| Limit | Value | Scope |
|-------|-------|-------|
| Requests per minute | 20 | Per conversation |
| Requests per hour | 200 | Per IP address |
| Max message length | 2000 chars | Per message |

### Rate Limit Response

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 60

{
  "success": false,
  "error": "Rate limit exceeded. Please wait before sending another message."
}
```

---

## Testing the API

### cURL Examples

**Health check:**
```bash
curl https://api.erleah.com/health
```

**Send message:**
```bash
curl -X POST https://api.erleah.com/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "conversation_id": "550e8400-e29b-41d4-a716-446655440000",
    "message_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
    "conference_id": "f47ac10b-58cc-4372-a567-0e02b2c3d479"
  }'
```

### Postman Collection

A Postman collection will be provided separately with all endpoints pre-configured.

---

## Monitoring & Debugging

### Request Tracing

Every request includes a trace ID in the response headers:

```http
X-Request-ID: abc123-def456-ghi789
```

Use this ID when reporting issues.

### Debug Mode

In development, add `?debug=true` to see additional info:

```bash
curl "https://api.erleah.com/api/chat?debug=true" \
  -X POST \
  -H "Content-Type: application/json" \
  -d '{"conversation_id": "...", ...}'
```

Response includes:
```json
{
  "success": true,
  "assistant_message_id": "...",
  "debug": {
    "intent": "session_search",
    "tools_used": ["search_sessions"],
    "processing_time_ms": 2340,
    "search_results_count": 5
  }
}
```

---

## Changelog

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2025-01-15 | Initial API specification |
