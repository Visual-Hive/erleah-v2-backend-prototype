# Phase 3: Model Selector + Groq Integration

## Goal
Swap LLMs per pipeline node at runtime. Add Groq as a provider to find the speed/quality sweet spot for each step.

## Depends On
Phase 1 (pipeline visibility + Svelte app scaffold)

## Backend Changes

### 3.1 LLM Registry
**New file:** `src/agent/llm_registry.py`

A runtime-configurable model registry that replaces the hardcoded `sonnet`/`haiku` imports:

```python
class LLMRegistry:
    """Runtime-configurable LLM registry. One model per node."""
    
    _models: dict[str, ModelConfig]
    # ModelConfig = {provider, model_id, display_name, instance}
    
    def get_model(self, node: str) -> BaseChatModel:
        """Get the LLM instance for a given node."""
    
    def set_model(self, node: str, provider: str, model_id: str) -> ModelConfig:
        """Change the model for a node. Creates new LLM instance."""
    
    def list_available(self) -> list[ModelOption]:
        """Return all available models across providers."""
    
    def get_config(self) -> dict[str, ModelConfig]:
        """Return current model assignments per node."""
```

### 3.2 Available Models

| Provider | Model ID | Display Name | Speed |
|---|---|---|---|
| `anthropic` | `claude-sonnet-4-20250514` | Claude Sonnet 4 | Medium |
| `anthropic` | `claude-haiku-4-5-20251001` | Claude Haiku 4.5 | Fast |
| `groq` | `llama-3.3-70b-versatile` | Llama 3.3 70B | Very Fast |
| `groq` | `llama-3.1-8b-instant` | Llama 3.1 8B | Ultra Fast |
| `groq` | `mixtral-8x7b-32768` | Mixtral 8x7B | Very Fast |

### 3.3 Default Node Assignments

| Node | Default Model | Why |
|---|---|---|
| `plan_queries` | Claude Sonnet 4 | Needs strong JSON planning |
| `generate_response` | Claude Sonnet 4 | Quality user-facing text |
| `evaluate` | Claude Haiku 4.5 | Simple scoring, cheap |
| `update_profile` | Claude Sonnet 4 | Needs reasoning |
| `generate_acknowledgment` | Grok 3 Mini | Quick ack, low stakes |

### 3.4 Groq Integration
**File:** `src/config.py` — add Groq settings:
```python
groq_api_key: str = ""
```

**File:** `.env` — add:
```
GROQ_API_KEY=gsk_your_groq_api_key_here
```

Groq uses OpenAI-compatible API via `langchain-groq`:
```python
from langchain_groq import ChatGroq

groq_llama_70b = ChatGroq(
    model="llama-3.3-70b-versatile",
    api_key=settings.groq_api_key,
    temperature=0,
)
```

**Dependency:** Add `langchain-groq` to `pyproject.toml`.

### 3.5 Debug API Endpoints
**File:** `src/api/debug.py` — add model endpoints:

```
GET  /api/debug/models
  → Returns available models + current assignments
  Response: {
    "available": [
      {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514", "name": "Claude Sonnet 4"},
      {"provider": "groq", "model_id": "llama-3.3-70b-versatile", "name": "Llama 3.3 70B"},
      ...
    ],
    "assignments": {
      "plan_queries": {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514"},
      "generate_response": {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514"},
      "evaluate": {"provider": "anthropic", "model_id": "claude-haiku-4-5-20251001"},
      ...
    }
  }

PUT  /api/debug/models/{node}
  → Change model for a node
  Body: {"provider": "groq", "model_id": "llama-3.3-70b-versatile"}
  Response: {"node": "evaluate", "provider": "groq", "model_id": "llama-3.3-70b-versatile"}

POST /api/debug/models/reset
  → Reset all to defaults
```

### 3.6 Wire Registry Into Nodes
**Modify** each LLM node to use the registry instead of direct imports:

```python
# Before:
from src.agent.llm import sonnet
result = await sonnet.ainvoke([...])

# After:
from src.agent.llm_registry import get_llm_registry
registry = get_llm_registry()
llm = registry.get_model("plan_queries")
result = await llm.ainvoke([...])
```

### Files to Create/Modify
- `src/agent/llm_registry.py` — **NEW**
- `src/api/debug.py` — **MODIFY** (add model endpoints)
- `src/config.py` — **MODIFY** (add groq_api_key)
- `.env` — **MODIFY** (add GROQ_API_KEY)
- `pyproject.toml` — **MODIFY** (add langchain-groq dep)
- `src/agent/nodes/plan_queries.py` — **MODIFY** (use registry)
- `src/agent/nodes/generate_response.py` — **MODIFY** (use registry)
- `src/agent/nodes/evaluate.py` — **MODIFY** (use registry)
- `src/agent/nodes/update_profile.py` — **MODIFY** (use registry)

## Frontend Components

### 3.7 ModelSelector Component
**New file:** `devtools/src/components/ModelSelector.svelte`

Features:
- **Table/grid** showing each LLM node with a dropdown to select model
- Each row: `[Node Name] [Current Model ▼] [Speed Badge] [Last Duration]`
- Dropdown shows all available models grouped by provider
- **Apply** saves via PUT to `/api/debug/models/{node}`
- **Reset All** button
- Visual indicator when a node is using a non-default model

### 3.8 Update Config Store
**Modify:** `devtools/src/lib/stores/config.js`

Add model assignments alongside prompts:
```javascript
{
  prompts: { ... },
  models: {
    available: [...],
    assignments: {
      "plan_queries": { provider: "anthropic", model_id: "claude-sonnet-4-20250514" },
      ...
    }
  }
}
```

### Files to Create/Modify
- `devtools/src/components/ModelSelector.svelte` — **NEW**
- `devtools/src/lib/stores/config.js` — **MODIFY**

## Acceptance Criteria
- [ ] See current model assignment for each LLM node
- [ ] Change a node's model via dropdown (e.g., evaluate → Groq Llama 70B)
- [ ] Next pipeline run uses the new model
- [ ] Node detail panel shows which model was used
- [ ] Duration difference visible between Anthropic vs Groq runs
- [ ] Reset all models to defaults
