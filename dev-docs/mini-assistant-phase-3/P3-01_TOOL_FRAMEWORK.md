# P3-01: Tool Framework
## Base Tool Class, Registry, and Planner Integration

**Priority:** 🔴 Required (foundation for all Phase 3 tools)  
**Effort:** 1 day  
**Dependencies:** TASK-01 (graceful failure), TASK-04 (Directus integration)  

---

## Goal

Create a tool framework that lets the LangGraph agent decide to use tools during the planning and execution phases. This is different from the existing pipeline nodes — tools are optional capabilities that the agent invokes based on conversational context, not fixed steps that run every time.

---

## Architecture

### How Tools Fit Into the Existing Pipeline

The current 9-node pipeline handles search queries. Tools extend this for actions that go beyond search:

```
fetch_data → acknowledgment → plan_queries → execute_queries → ...
                                    │
                                    ▼
                            Planner now also detects
                            "tool-requiring intents"
                            like registration requests
                                    │
                                    ▼
                            If tools needed:
                            execute_tools node (NEW)
                            runs before or instead of
                            execute_queries
```

### Two Integration Approaches

**Option A: Tools as part of plan_queries output** (recommended for now)

The planner already classifies intent and generates queries. Extend it to also generate tool calls when appropriate. The `execute_queries` node (or a new sibling node) handles tool execution.

```python
# Planner output with tools
{
    "intent": "registration_data_request",
    "needs_tools": True,
    "tool_calls": [
        {
            "tool": "lookup_registration",
            "args": {"identifier": "john@example.com"},
            "reason": "User wants badge resent, need to find their registration"
        }
    ],
    "queries": []  # No search queries needed for this intent
}
```

**Option B: Full agentic tool loop** (future, when more tools exist)

A `reflect` node that can loop back and call additional tools. This is the architecture in the technical spec (understand → plan → execute → reflect → respond) but is overkill for 2 tools.

**Start with Option A. It requires minimal changes to the existing pipeline.**

---

## Implementation

### 1. Base Tool Class

```python
# src/tools/base.py

from abc import ABC, abstractmethod
from typing import Any
import structlog

logger = structlog.get_logger()


class BaseTool(ABC):
    """
    Base class for all agent tools.
    
    Tools are different from pipeline nodes:
    - Nodes run every request in a fixed order
    - Tools are invoked by the agent when needed
    - Tools return data that the agent uses to form a response
    - Tools never write to the chat directly — the agent does that
    """
    
    name: str
    description: str  # Used by the planner to decide when to invoke
    
    # Security classification
    requires_identifier: bool = False  # Does the user need to provide an identifier?
    returns_private_data: bool = False # Does this tool handle private data?
    rate_limit_key: str | None = None  # Rate limit group (e.g. "email_send")
    
    @abstractmethod
    async def execute(self, args: dict[str, Any], context: dict) -> dict[str, Any]:
        """
        Execute the tool.
        
        Args:
            args: Tool-specific arguments
            context: Pipeline context (trace_id, conversation_id, etc.)
        
        Returns:
            {
                "success": True/False,
                "data": { ... tool-specific result ... },
                "error": None or error message,
                "user_message": Optional message for the agent to relay
            }
        """
        pass
    
    async def safe_execute(self, args: dict[str, Any], context: dict) -> dict[str, Any]:
        """Execute with error handling — never crashes the pipeline."""
        try:
            logger.info(
                "tool_execute",
                tool=self.name,
                trace_id=context.get("trace_id"),
                # Don't log args — may contain PII
            )
            result = await self.execute(args, context)
            logger.info(
                "tool_complete",
                tool=self.name,
                success=result.get("success"),
                trace_id=context.get("trace_id"),
            )
            return result
        except Exception as e:
            logger.error(
                "tool_error",
                tool=self.name,
                error=str(e),
                trace_id=context.get("trace_id"),
            )
            return {
                "success": False,
                "data": None,
                "error": f"Tool '{self.name}' encountered an error",
                "user_message": "I ran into a problem looking that up. Could you try again?",
            }
```

### 2. Tool Registry

```python
# src/tools/registry.py

from typing import Any
import structlog
from src.tools.base import BaseTool

logger = structlog.get_logger()

_TOOLS: dict[str, BaseTool] = {}


def register_tool(tool: BaseTool):
    """Register a tool in the global registry."""
    _TOOLS[tool.name] = tool
    logger.info("tool_registered", name=tool.name)


def get_tool(name: str) -> BaseTool | None:
    """Get a tool by name."""
    return _TOOLS.get(name)


def get_all_tools() -> dict[str, BaseTool]:
    """Get all registered tools."""
    return _TOOLS.copy()


def get_tool_descriptions() -> list[dict]:
    """
    Get descriptions of all tools for the planner prompt.
    
    The planner uses these to decide which tools to invoke.
    """
    return [
        {
            "name": tool.name,
            "description": tool.description,
            "requires_identifier": tool.requires_identifier,
        }
        for tool in _TOOLS.values()
    ]


def initialize_tools():
    """Register all available tools. Called on app startup."""
    # Import and register tools here
    from src.tools.registration_lookup import RegistrationLookupTool
    from src.tools.registration_email import SendRegistrationEmailTool
    
    register_tool(RegistrationLookupTool())
    register_tool(SendRegistrationEmailTool())
    
    logger.info("tools_initialized", count=len(_TOOLS))
```

### 3. Planner Integration

Update the planner system prompt to be aware of tools:

```python
# Add to the planner prompt (in prompt_registry)

TOOL_AWARENESS_PROMPT = """
## Available Tools

In addition to searching conference data, you have access to these tools:

{tool_descriptions}

When a user's request requires a tool (e.g. resending a badge, invoice, or 
registration confirmation), output a tool_calls array instead of or alongside queries.

Tool call format:
{{
    "tool_calls": [
        {{
            "tool": "tool_name",
            "args": {{ "arg_name": "value" }},
            "reason": "Why this tool is needed"
        }}
    ]
}}

IMPORTANT: If the user hasn't provided the required identifier (email or registration ID) 
yet, do NOT call the tool. Instead, set:
{{
    "needs_user_input": true,
    "input_request": "I'd be happy to help! Could you provide your registration email or registration ID?"
}}
"""
```

### 4. Execute Tools Node

Add a tool execution step. This can be a conditional branch from plan_queries:

```python
# src/agent/nodes/execute_tools.py

import structlog
from src.tools.registry import get_tool
from src.agent.state import AssistantState

logger = structlog.get_logger()


async def execute_tools(state: AssistantState) -> dict:
    """
    Execute tools requested by the planner.
    
    Runs after plan_queries if the plan includes tool_calls.
    """
    tool_calls = state.get("tool_calls", [])
    
    if not tool_calls:
        return {"tool_results": {}}
    
    results = {}
    context = {
        "trace_id": state.get("trace_id"),
        "conversation_id": state.get("conversation_context", {}).get("conversation_id"),
        "conference_id": state.get("user_context", {}).get("conference_id"),
    }
    
    for call in tool_calls:
        tool_name = call.get("tool")
        tool_args = call.get("args", {})
        
        tool = get_tool(tool_name)
        if not tool:
            logger.warning("tool_not_found", name=tool_name)
            results[tool_name] = {
                "success": False,
                "error": f"Unknown tool: {tool_name}",
            }
            continue
        
        result = await tool.safe_execute(tool_args, context)
        results[tool_name] = result
    
    return {"tool_results": results}
```

### 5. Pipeline Wiring

Add the conditional branch in `graph.py`:

```python
def should_execute_tools(state: AssistantState) -> str:
    """Route to tool execution if planner requested tools."""
    if state.get("tool_calls"):
        return "execute_tools"
    if state.get("needs_user_input"):
        return "generate_response"  # Agent asks user for input
    return "execute_queries"  # Normal search flow

# Wire: plan_queries → conditional → execute_tools OR execute_queries
graph_builder.add_conditional_edges(
    "plan_queries",
    should_execute_tools,
    {
        "execute_tools": "execute_tools",
        "execute_queries": "execute_queries",
        "generate_response": "generate_response",
    },
)

# execute_tools → generate_response (tools go straight to response, no search needed)
graph_builder.add_edge("execute_tools", "generate_response")
```

### 6. State Extensions

```python
# Add to AssistantState

class AssistantState(TypedDict):
    # ... existing fields ...
    
    # Tool system
    tool_calls: list[dict] | None       # From planner: [{tool, args, reason}]
    tool_results: dict[str, dict]       # Results from tool execution
    needs_user_input: bool              # Planner needs more info from user
    input_request: str | None           # What to ask the user
```

---

## Testing

```python
async def test_tool_safe_execute_never_crashes():
    """Tool errors should return error dict, not raise."""
    class BrokenTool(BaseTool):
        name = "broken"
        description = "always fails"
        async def execute(self, args, context):
            raise RuntimeError("kaboom")
    
    tool = BrokenTool()
    result = await tool.safe_execute({}, {"trace_id": "test"})
    assert result["success"] is False
    assert result["error"] is not None

def test_tool_registry():
    """Tools should be retrievable by name."""
    initialize_tools()
    assert get_tool("lookup_registration") is not None

def test_planner_tool_descriptions():
    """Tool descriptions should be formatted for the planner prompt."""
    initialize_tools()
    descriptions = get_tool_descriptions()
    assert len(descriptions) >= 2
    assert all("name" in d for d in descriptions)
```

---

## Acceptance Criteria

- [ ] `BaseTool` abstract class with `execute()` and `safe_execute()`
- [ ] `safe_execute()` never raises — always returns a result dict
- [ ] Tool registry with `register_tool()`, `get_tool()`, `get_tool_descriptions()`
- [ ] Tools initialized on app startup
- [ ] Planner prompt includes tool descriptions
- [ ] Planner can output `tool_calls` and `needs_user_input`
- [ ] `execute_tools` node runs tool calls and stores results
- [ ] Conditional edge: plan → tools or plan → queries based on planner output
- [ ] Tool results available to `generate_response` for crafting the reply
- [ ] State extended with `tool_calls`, `tool_results`, `needs_user_input`
- [ ] Unit tests for base tool, registry, and error handling
