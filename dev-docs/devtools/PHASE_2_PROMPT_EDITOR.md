# Phase 2: Prompt Editor

## Goal
View, edit, and hot-reload system prompts for each LLM node. Compare prompt performance across runs.

## Depends On
Phase 1 (pipeline visibility + Svelte app scaffold)

## Backend Changes

### 2.1 Prompt Registry
**New file:** `src/agent/prompt_registry.py`

A runtime-mutable store of system prompts, initialized from `prompts.py` defaults:

```python
class PromptRegistry:
    """Runtime-mutable prompt store."""
    
    _prompts: dict[str, PromptConfig]  # node_name → {text, version, updated_at}
    
    def get(self, node: str) -> str:
        """Get current prompt text for a node."""
    
    def update(self, node: str, text: str) -> PromptConfig:
        """Update prompt, bump version, return new config."""
    
    def list_all(self) -> dict[str, PromptConfig]:
        """Return all prompts with metadata."""
    
    def reset(self, node: str) -> PromptConfig:
        """Reset prompt to default from prompts.py."""
```

Prompt nodes and their prompts:

| Node | Prompt Key | Default Source |
|---|---|---|
| `plan_queries` | `plan_queries` | `PLAN_QUERIES_SYSTEM` |
| `generate_response` | `generate_response` | `GENERATE_RESPONSE_SYSTEM` |
| `evaluate` | `evaluate` | `EVALUATE_SYSTEM` |
| `update_profile` | `profile_detect` | `PROFILE_DETECT_SYSTEM` |
| `update_profile` | `profile_update` | `PROFILE_UPDATE_SYSTEM` |
| `generate_acknowledgment` | `acknowledgment` | (inline in grok.py) |

### 2.2 Debug API Endpoints
**New file:** `src/api/debug.py`

```
GET  /api/debug/prompts
  → Returns all prompts with metadata
  Response: {
    "plan_queries": {
      "text": "You are a search-planning assistant...",
      "version": 1,
      "updated_at": "2026-02-06T19:00:00Z",
      "is_default": true,
      "node": "plan_queries"
    },
    ...
  }

GET  /api/debug/prompts/{node}
  → Returns single prompt
  Response: { "text": "...", "version": 1, ... }

PUT  /api/debug/prompts/{node}
  → Update prompt text (runtime override, not persisted to disk)
  Body: { "text": "New prompt text..." }
  Response: { "text": "...", "version": 2, "is_default": false }

POST /api/debug/prompts/{node}/reset
  → Reset to default from prompts.py
  Response: { "text": "...", "version": 3, "is_default": true }
```

### 2.3 Wire Prompts Into Nodes
**Modify:** Each LLM node to read from `PromptRegistry` instead of importing constants.

Example change in `plan_queries.py`:
```python
# Before:
from src.agent.prompts import PLAN_QUERIES_SYSTEM
SystemMessage(content=PLAN_QUERIES_SYSTEM, ...)

# After:
from src.agent.prompt_registry import get_prompt_registry
registry = get_prompt_registry()
SystemMessage(content=registry.get("plan_queries"), ...)
```

### 2.4 Include Prompt Version in Debug Events
Enhance `node_end` SSE events to include `prompt_version`:
```json
{
  "node": "plan_queries",
  "prompt_version": 2,
  ...
}
```

### Files to Create/Modify
- `src/agent/prompt_registry.py` — **NEW**
- `src/api/debug.py` — **NEW** (add prompt endpoints)
- `src/main.py` — **MODIFY** (mount debug router)
- `src/agent/nodes/plan_queries.py` — **MODIFY** (use registry)
- `src/agent/nodes/generate_response.py` — **MODIFY** (use registry)
- `src/agent/nodes/evaluate.py` — **MODIFY** (use registry)
- `src/agent/nodes/update_profile.py` — **MODIFY** (use registry)

## Frontend Components

### 2.5 PromptEditor Component
**New file:** `devtools/src/components/PromptEditor.svelte`

Features:
- **Dropdown** to select which node's prompt to view/edit
- **Text editor** (textarea or CodeMirror via CDN) showing the prompt
- **Save button** → PUT to `/api/debug/prompts/{node}`
- **Reset button** → POST to `/api/debug/prompts/{node}/reset`
- **Version badge** showing current version number
- **"Default" / "Modified" indicator**
- **Character/word count** for prompt length awareness

Layout: Lives in the right panel of the DevTools UI, toggled via a tab.

### 2.6 Prompt Store
**New file:** `devtools/src/lib/stores/config.js`

```javascript
// Stores prompt config fetched from backend
{
  prompts: {
    "plan_queries": { text: "...", version: 1, is_default: true },
    "generate_response": { text: "...", version: 1, is_default: true },
    ...
  }
}
```

### Files to Create
- `devtools/src/components/PromptEditor.svelte` — **NEW**
- `devtools/src/lib/stores/config.js` — **NEW**

## Acceptance Criteria
- [ ] View all system prompts in the DevTools UI
- [ ] Edit a prompt and save → next pipeline run uses updated prompt
- [ ] Reset a prompt to its default
- [ ] See prompt version number in node detail panel
- [ ] Modified prompts show "Modified" indicator
