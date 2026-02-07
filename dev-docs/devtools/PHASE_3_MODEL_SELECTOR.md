# Phase 3: Model Selector + Groq Integration ✅ COMPLETE

> **Status:** Implemented and verified  
> **Completed:** 2026-02-07  
> **Version:** v0.3.0

## Goal
Swap LLMs per pipeline node at runtime. Add Groq as a provider to find the speed/quality sweet spot for each step.

## Depends On
Phase 1 (pipeline visibility + Svelte app scaffold)

---

## Backend Changes

### 3.1 LLM Registry ✅
**New file:** `src/agent/llm_registry.py`

A runtime-configurable model registry that replaces the hardcoded `sonnet`/`haiku` imports. Uses a singleton pattern with lazy LLM instantiation:

```python
class LLMRegistry:
    """Runtime-configurable LLM registry. One model per node."""
    
    _assignments: dict[str, NodeAssignment]
    # NodeAssignment = {provider, model_id, display_name, speed, is_default, instance}
    
    def get_model(self, node: str) -> BaseChatModel:
        """Get the LLM instance for a given node. Lazy-creates on first call."""
    
    def get_model_info(self, node: str) -> dict:
        """Get model metadata for a node (for debug events)."""
    
    def set_model(self, node: str, provider: str, model_id: str) -> dict:
        """Change the model for a node. Creates new LLM instance."""
    
    def list_available(self) -> list[dict]:
        """Return all available models across providers (with availability check)."""
    
    def get_assignments(self) -> dict:
        """Return current model assignments per node."""
    
    def reset_all(self) -> dict:
        """Reset all nodes to default model assignments."""

# Module-level singleton accessor
def get_llm_registry() -> LLMRegistry:
    """Get or create the global LLM registry singleton."""
```

**Implementation details:**
- Singleton via module-level `_registry` variable
- Each assignment tracks: `provider`, `model_id`, `display_name`, `speed`, `is_default`, `instance`
- `_create_llm()` factory handles both Anthropic and Groq providers
- Groq import is lazy (`from langchain_groq import ChatGroq`) — only loaded when switching to a Groq model
- `list_available()` checks for API key presence and marks models as `available: true/false`

### 3.2 Available Models ✅

| Provider | Model ID | Display Name | Speed | Available When |
|---|---|---|---|---|
| `anthropic` | `claude-sonnet-4-20250514` | Claude Sonnet 4 | Medium | `ANTHROPIC_API_KEY` set |
| `anthropic` | `claude-haiku-4-5-20251001` | Claude Haiku 4.5 | Fast | `ANTHROPIC_API_KEY` set |
| `groq` | `llama-3.3-70b-versatile` | Llama 3.3 70B | Very Fast | `GROQ_API_KEY` set |
| `groq` | `llama-3.1-8b-instant` | Llama 3.1 8B | Ultra Fast | `GROQ_API_KEY` set |
| `groq` | `mixtral-8x7b-32768` | Mixtral 8x7B | Very Fast | `GROQ_API_KEY` set |

### 3.3 Default Node Assignments ✅

| Node | Default Model | Why |
|---|---|---|
| `plan_queries` | Claude Sonnet 4 | Needs strong JSON planning |
| `generate_response` | Claude Sonnet 4 | Quality user-facing text |
| `evaluate` | Claude Haiku 4.5 | Simple scoring, cheap |
| `update_profile` | Claude Sonnet 4 | Needs reasoning |
| `generate_acknowledgment` | Grok 3 Mini (xAI) | Quick ack — **not managed by registry** |

> **Note:** `generate_acknowledgment` uses xAI/Grok directly via `src/services/grok.py` and is not part of the LLM registry. It could be added in a future iteration.

### 3.4 Groq Integration ✅
**File:** `src/config.py` — added Groq settings:
```python
groq_api_key: str = ""
```

**File:** `.env.example` — added:
```
GROQ_API_KEY=gsk_your_groq_api_key_here
```

**File:** `pyproject.toml` — added dependency:
```toml
"langchain-groq>=0.2.0",
```

Groq uses the `langchain-groq` package with `ChatGroq`:
```python
from langchain_groq import ChatGroq
llm = ChatGroq(model=model_id, api_key=settings.groq_api_key, temperature=0)
```

### 3.5 Debug API Endpoints ✅
**File:** `src/api/debug.py` — added 3 model endpoints:

```
GET  /api/debug/models
  → Returns available models + current node assignments
  Response: {
    "available": [
      {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514", 
       "display_name": "Claude Sonnet 4", "speed": "Medium", "available": true},
      {"provider": "groq", "model_id": "llama-3.3-70b-versatile", 
       "display_name": "Llama 3.3 70B", "speed": "Very Fast", "available": true},
      ...
    ],
    "assignments": {
      "plan_queries": {"provider": "anthropic", "model_id": "claude-sonnet-4-20250514", 
                        "display_name": "Claude Sonnet 4", "speed": "Medium", "is_default": true},
      ...
    }
  }

PUT  /api/debug/models/{node}
  → Change model for a specific node
  Body: {"provider": "groq", "model_id": "llama-3.3-70b-versatile"}
  Response: {"node": "evaluate", "provider": "groq", "model_id": "llama-3.3-70b-versatile",
             "display_name": "Llama 3.3 70B", "speed": "Very Fast", "is_default": false}

POST /api/debug/models/reset
  → Reset all nodes to default model assignments
  Response: {"assignments": { ... }}  (all nodes with is_default: true)
```

### 3.6 Wire Registry Into Nodes ✅
All 4 LLM nodes now use the registry:

```python
# Before (hardcoded):
from src.agent.llm import sonnet
result = await sonnet.ainvoke([...])

# After (registry):
from src.agent.llm_registry import get_llm_registry
registry = get_llm_registry()
llm = registry.get_model("plan_queries")
result = await llm.ainvoke([...])
```

### 3.7 Enhanced Debug Events ✅
**File:** `src/agent/graph.py`

`node_start` events now include model info for LLM nodes:
```json
{
  "event": "node_start",
  "data": {
    "node": "plan_queries",
    "ts": 1234567890.123,
    "model": {
      "provider": "anthropic",
      "model_id": "claude-sonnet-4-20250514",
      "display_name": "Claude Sonnet 4",
      "is_default": true
    }
  }
}
```

### Files Created/Modified ✅

| File | Action | What Changed |
|---|---|---|
| `src/agent/llm_registry.py` | **NEW** | Runtime-configurable model registry |
| `src/api/debug.py` | **MODIFIED** | Added 3 model API endpoints |
| `src/config.py` | **MODIFIED** | Added `groq_api_key` setting |
| `.env.example` | **MODIFIED** | Added `GROQ_API_KEY` |
| `pyproject.toml` | **MODIFIED** | Added `langchain-groq` dependency |
| `src/agent/nodes/plan_queries.py` | **MODIFIED** | Uses `get_llm_registry().get_model("plan_queries")` |
| `src/agent/nodes/generate_response.py` | **MODIFIED** | Uses `get_llm_registry().get_model("generate_response")` |
| `src/agent/nodes/evaluate.py` | **MODIFIED** | Uses `get_llm_registry().get_model("evaluate")` |
| `src/agent/nodes/update_profile.py` | **MODIFIED** | Uses `get_llm_registry().get_model("update_profile")` |
| `src/agent/graph.py` | **MODIFIED** | Emits model info in `node_start` events |

---

## Frontend Components

### 3.8 ModelSelector Component ✅
**New file:** `devtools/src/components/ModelSelector.svelte`

Features implemented:
- **Card-per-node layout** showing each LLM node with a `<select>` dropdown
- Each card: `[Icon] [Node Name] [Custom badge] [Speed Badge]`
- Dropdown shows all available models with provider + speed info
- Unavailable models (no API key) shown but disabled with `⚠ No API key` label
- **Apply** button appears when selection differs from current — saves via PUT
- **Reset All** button (red, top-right) — resets all to defaults
- **Refresh** button to re-fetch from backend
- **Visual indicators:**
  - Yellow border for nodes with pending unsaved changes
  - Yellow "Custom" badge for non-default model assignments
  - Green flash animation on successful save
  - Provider badge (orange for Anthropic, cyan for Groq)
  - Speed badge with color-coded tiers
- **Modified count badge** on "🧠 Models" tab showing how many nodes are non-default
- Info box at bottom explaining how model switching works

### 3.9 Updated Config Store ✅
**Modified:** `devtools/src/lib/stores/config.js`

Added model-related stores:
```javascript
export const availableModels = writable([]);    // All models across providers
export const modelAssignments = writable({});   // Current node → model mapping
export const modelsLoading = writable(false);
export const modelsError = writable(null);

// Derived: count of non-default assignments
export const nonDefaultModelCount = derived(modelAssignments, ($a) =>
  Object.values($a).filter((m) => !m.is_default).length
);
```

### 3.10 Updated API Client ✅
**Modified:** `devtools/src/lib/api.js`

Added 3 functions:
- `fetchModels()` — GET available models + assignments, populates stores
- `updateModel(node, provider, modelId)` — PUT to change a node's model
- `resetModels()` — POST to reset all to defaults

### 3.11 Updated NodeDetail ✅
**Modified:** `devtools/src/components/NodeDetail.svelte`

Added "Assigned Model" section showing:
- Model display name + "Custom" badge if non-default
- Provider + model_id in monospace

### 3.12 Updated Pipeline Store ✅
**Modified:** `devtools/src/lib/stores/pipeline.js`

`handleNodeStart()` now captures the `model` field from debug events.

### Frontend Files Created/Modified ✅

| File | Action | What Changed |
|---|---|---|
| `devtools/src/components/ModelSelector.svelte` | **NEW** | Model selector UI component |
| `devtools/src/App.svelte` | **MODIFIED** | Added "🧠 Models" tab (3rd tab), v0.3.0 |
| `devtools/src/lib/stores/config.js` | **MODIFIED** | Added model stores + derived count |
| `devtools/src/lib/api.js` | **MODIFIED** | Added fetchModels, updateModel, resetModels |
| `devtools/src/components/NodeDetail.svelte` | **MODIFIED** | Shows assigned model info |
| `devtools/src/lib/stores/pipeline.js` | **MODIFIED** | Captures model from node_start |

---

## Acceptance Criteria

- [x] See current model assignment for each LLM node
- [x] Change a node's model via dropdown (e.g., evaluate → Groq Llama 70B)
- [x] Next pipeline run uses the new model
- [x] Node detail panel shows which model was used
- [x] Duration difference visible between Anthropic vs Groq runs
- [x] Reset all models to defaults

## Verified End-to-End

Tested with live backend:
1. **Switched evaluate node** to Groq Llama 3.3 70B → API returned 200, model changed
2. **Ran pipeline** ("howdy") → evaluate node used `llama-3.3-70b-versatile` (381ms vs typical ~1500ms with Haiku)
3. **Reset all** → All nodes back to Anthropic defaults
4. **Groq models** correctly marked unavailable when `GROQ_API_KEY` not set
