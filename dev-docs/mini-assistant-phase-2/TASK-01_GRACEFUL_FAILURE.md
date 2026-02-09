# TASK-01: Graceful Failure System
## "The Agent Always Responds"

**Priority:** 🔴 Critical — do this first, everything else depends on it  
**Effort:** 1-2 days  
**Dependencies:** None  

---

## Goal

No matter what goes wrong in the Python backend — Qdrant timeout, Directus down, LLM rate limit, malformed data, unexpected exception — the **generate_response** node must always produce a coherent, helpful message back to the user. The conversation must never dead-end.

This is philosophically different from typical error handling. We're not just catching errors and logging them. We're ensuring the LLM agent is **informed about the failure** so it can tell the user what happened and suggest next steps, in natural language, within the conversation flow.

---

## Architecture

### Error Context Object

Create a standardized error context that any node can populate when something goes wrong. This context gets passed forward in the LangGraph state and is available to `generate_response`.

```python
# src/agent/state.py — add to AssistantState

class ErrorContext(TypedDict, total=False):
    """Context about failures that the response generator can use."""
    failed_node: str                    # Which node failed
    error_type: str                     # Category: "timeout", "connection", "rate_limit", "data", "unknown"
    error_detail: str                   # Technical detail (for logs, not user)
    user_hint: str                      # Pre-written hint for the agent
    degraded_results: bool              # True if we have partial results
    available_data: list[str]           # What data DID load successfully
    unavailable_data: list[str]         # What data failed to load
    can_retry: bool                     # Whether retrying might help
    retry_suggestion: str               # e.g. "Try rephrasing your question"
```

Add to `AssistantState`:
```python
class AssistantState(TypedDict):
    # ... existing fields ...
    error_context: Optional[ErrorContext]    # None = no errors
    partial_failure: bool                    # True = some things worked, some didn't
```

### Error-Aware Response Generation

The key insight: **don't generate a canned error message**. Instead, give the error context to the LLM and let it craft a natural response.

Add to the `generate_response` system prompt:

```
## Error Awareness

If error information is provided below, you must acknowledge the issue naturally 
and helpfully. Never show technical details. Instead:
- Explain what you were able to do and what you couldn't
- Suggest what the user can do (rephrase, try again, ask something simpler)
- Stay warm and helpful — never apologize excessively
- If you have partial results, present what you have and note what's missing

Error context (if any): {error_context_json}
```

---

## Implementation

### 1. Node-Level Error Wrapping

Every node should catch its own errors and populate `error_context` instead of crashing the pipeline.

Create a decorator:

```python
# src/agent/nodes/error_wrapper.py

import functools
import traceback
import structlog

logger = structlog.get_logger()

def graceful_node(node_name: str, critical: bool = False):
    """
    Wrap a LangGraph node so it never crashes the pipeline.
    
    Args:
        node_name: Name for logging and error context
        critical: If True, the pipeline cannot continue without this node.
                  If False, the pipeline continues with degraded results.
    """
    def decorator(func):
        @functools.wraps(func)
        async def wrapper(state, *args, **kwargs):
            try:
                return await func(state, *args, **kwargs)
            except Exception as e:
                logger.error(
                    f"node_failure",
                    node=node_name,
                    error=str(e),
                    critical=critical,
                    traceback=traceback.format_exc(),
                    trace_id=state.get("trace_id"),
                )
                
                error_context = build_error_context(node_name, e, state)
                
                if critical:
                    # Pipeline must stop, but still generate a response
                    return {
                        **state,
                        "error_context": error_context,
                        "partial_failure": True,
                        "force_response": True,  # Skip remaining nodes, go to response
                    }
                else:
                    # Continue with degraded data
                    return {
                        **state,
                        "error_context": error_context,
                        "partial_failure": True,
                    }
        return wrapper
    return decorator
```

### 2. Error Context Builder

```python
# src/agent/nodes/error_wrapper.py (continued)

def build_error_context(node_name: str, error: Exception, state: dict) -> dict:
    """Build a user-friendly error context from an exception."""
    
    error_type = classify_error(error)
    
    context = {
        "failed_node": node_name,
        "error_type": error_type,
        "error_detail": str(error),  # For logs only
        "degraded_results": True,
        "can_retry": error_type in ("timeout", "connection", "rate_limit"),
    }
    
    # Node-specific hints
    hints = {
        "fetch_data": {
            "timeout": "I wasn't able to load all the data I needed. I'll do my best with what I have.",
            "connection": "I'm having trouble reaching the database right now.",
        },
        "plan_queries": {
            "timeout": "My search planning is taking too long. I'll try a simpler approach.",
            "rate_limit": "I'm getting a lot of requests right now. Let me try a simpler search.",
        },
        "execute_queries": {
            "timeout": "The search is taking too long. I may have partial results.",
            "connection": "The search database isn't responding. I'll try to help with what I know.",
        },
        "generate_response": {
            "rate_limit": "I'm temporarily overloaded. Please try again in a moment.",
            "timeout": "I'm having trouble forming a response. Please try a shorter question.",
        },
    }
    
    node_hints = hints.get(node_name, {})
    context["user_hint"] = node_hints.get(error_type, "Something unexpected happened, but I'll try to help.")
    context["retry_suggestion"] = get_retry_suggestion(error_type)
    
    # Track what data is available
    context["available_data"] = []
    context["unavailable_data"] = []
    
    if state.get("user_profile"):
        context["available_data"].append("profile")
    else:
        context["unavailable_data"].append("profile")
    
    if state.get("conversation_history"):
        context["available_data"].append("conversation_history")
    else:
        context["unavailable_data"].append("conversation_history")
    
    if state.get("query_results"):
        non_empty = [k for k, v in state["query_results"].items() if v]
        context["available_data"].extend(non_empty)
    
    return context


def classify_error(error: Exception) -> str:
    """Classify an exception into a user-friendly category."""
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()
    
    if "timeout" in error_str or "timeout" in error_type:
        return "timeout"
    elif "connection" in error_str or "connect" in error_str:
        return "connection"
    elif "rate" in error_str or "429" in error_str or "quota" in error_str:
        return "rate_limit"
    elif "not found" in error_str or "404" in error_str:
        return "not_found"
    elif "validation" in error_str or "invalid" in error_str:
        return "data"
    else:
        return "unknown"


def get_retry_suggestion(error_type: str) -> str:
    """Suggest what the user should do."""
    suggestions = {
        "timeout": "You could try asking again — sometimes things are just briefly slow.",
        "connection": "This is usually temporary. Try again in a moment.",
        "rate_limit": "I'm busy right now. Please wait a minute and try again.",
        "not_found": "Try rephrasing your question or asking about something else.",
        "data": "Could you rephrase that? I had trouble understanding the request.",
        "unknown": "Try asking your question in a different way, or try again shortly.",
    }
    return suggestions.get(error_type, suggestions["unknown"])
```

### 3. Conditional Edge: Force Response on Critical Failure

Add a new conditional edge in `graph.py` that can skip straight to `generate_response` when a critical node fails:

```python
def should_force_response(state: AssistantState) -> str:
    """Skip to response generation if there's a critical failure."""
    if state.get("force_response"):
        return "generate_response"
    return "continue"  # Normal flow
```

Wire this after `fetch_data` and after `execute_queries` (the two most failure-prone points).

### 4. Last-Resort Error Handler

If even `generate_response` fails (LLM is completely down), have a hardcoded fallback:

```python
# src/agent/nodes/generate_response.py

LAST_RESORT_MESSAGES = {
    "timeout": "I'm sorry, I'm running a bit slow right now. Could you try asking your question again in a moment? If the problem persists, try a simpler question.",
    "connection": "I'm having trouble connecting to my services right now. This is usually temporary — please try again in a minute or two.",
    "rate_limit": "I'm receiving a lot of questions right now and need a moment to catch up. Please try again in about a minute.",
    "default": "I ran into an unexpected issue processing your question. Please try again, and if the problem continues, try rephrasing your question. I'm here to help!",
}

async def generate_response_with_fallback(state, ...):
    """Generate response, with hardcoded fallback if LLM fails."""
    try:
        return await generate_response(state, ...)
    except Exception as e:
        logger.error("response_generation_failed", error=str(e))
        error_type = classify_error(e)
        fallback = LAST_RESORT_MESSAGES.get(error_type, LAST_RESORT_MESSAGES["default"])
        
        return {
            **state,
            "assistant_response": fallback,
            "response_source": "fallback",
        }
```

### 5. Apply the Decorator to All Nodes

```python
# Example: fetch_data node

@graceful_node("fetch_data", critical=False)
async def fetch_data_parallel(state: AssistantState) -> dict:
    # ... existing implementation ...
    # If this crashes, pipeline continues with empty profile/history
    pass

@graceful_node("execute_queries", critical=False)
async def execute_queries(state: AssistantState) -> dict:
    # ... existing implementation ...
    # If this crashes, agent gets told "search failed" and can still respond
    pass

# generate_response uses its own fallback wrapper instead
```

---

## Health-Aware Agent (Bonus)

When health checks detect a degraded service (TASK-05), feed that info into the agent proactively:

```python
# Before entering the pipeline, check service health
health_status = await check_all_services()

if health_status.degraded_services:
    state["service_health"] = {
        "qdrant": health_status.qdrant,       # "ok" | "slow" | "down"
        "directus": health_status.directus,
        "anthropic": health_status.anthropic,
    }
```

The agent prompt can then include:
```
Service status: Qdrant is currently slow. Search results may be limited or delayed.
```

This way the agent preemptively manages expectations instead of being surprised by failures.

---

## Testing

### Unit Tests

```python
def test_error_classification():
    assert classify_error(TimeoutError("request timed out")) == "timeout"
    assert classify_error(ConnectionError("refused")) == "connection"
    assert classify_error(Exception("429 rate limit")) == "rate_limit"
    assert classify_error(Exception("something weird")) == "unknown"

async def test_graceful_node_catches_errors():
    @graceful_node("test_node", critical=False)
    async def failing_node(state):
        raise ConnectionError("Directus is down")
    
    result = await failing_node({"trace_id": "test"})
    assert result["partial_failure"] is True
    assert result["error_context"]["error_type"] == "connection"

async def test_last_resort_fallback():
    # Simulate LLM being completely down
    result = await generate_response_with_fallback(state_with_broken_llm)
    assert result["assistant_response"] != ""
    assert result["response_source"] == "fallback"
```

### Integration Tests

- Kill Qdrant → send message → verify user gets "search unavailable" response
- Kill Directus → send message → verify user gets "database unavailable" response  
- Set Anthropic key to invalid → send message → verify user gets fallback message
- Partial failure: Qdrant down but Directus up → verify agent mentions what it couldn't search

---

## Acceptance Criteria

- [ ] Every pipeline node is wrapped with `@graceful_node`
- [ ] `generate_response` has a last-resort hardcoded fallback
- [ ] Error context flows through state to the response generator
- [ ] The agent's system prompt includes error awareness instructions
- [ ] The user NEVER sees a raw error, stack trace, or dead-end
- [ ] Partial failures produce degraded-but-coherent responses
- [ ] All error types are classified and have user-friendly hints
- [ ] Health status can be injected into agent context (for TASK-05)
- [ ] Unit tests cover all error classification paths
- [ ] Integration test: kill each external service and verify graceful response
