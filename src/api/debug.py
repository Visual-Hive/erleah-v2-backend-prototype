"""Debug API endpoints for the Erleah DevTools.

Provides prompt viewing/editing and pipeline configuration.
These endpoints are additive — they don't affect the production chat API.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.agent.llm_registry import get_llm_registry
from src.agent.prompt_registry import get_prompt_registry

router = APIRouter(tags=["debug"])


class PromptUpdateRequest(BaseModel):
    """Request body for updating a prompt."""

    text: str


# ── Prompt endpoints ──


@router.get("/prompts")
async def list_prompts() -> dict:
    """Return all prompts with metadata."""
    registry = get_prompt_registry()
    return registry.list_all()


@router.get("/prompts/{key}")
async def get_prompt(key: str) -> dict:
    """Return a single prompt by key."""
    registry = get_prompt_registry()
    try:
        config = registry.get_config(key)
        return config.to_dict()
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown prompt key: {key}")


@router.put("/prompts/{key}")
async def update_prompt(key: str, body: PromptUpdateRequest) -> dict:
    """Update a prompt's text. Takes effect on the next pipeline run."""
    registry = get_prompt_registry()
    try:
        config = registry.update(key, body.text)
        return config.to_dict()
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown prompt key: {key}")


@router.post("/prompts/{key}/reset")
async def reset_prompt(key: str) -> dict:
    """Reset a prompt to its default text from prompts.py."""
    registry = get_prompt_registry()
    try:
        config = registry.reset(key)
        return config.to_dict()
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Unknown prompt key: {key}")


# ── Model endpoints ──


class ModelUpdateRequest(BaseModel):
    """Request body for changing a node's model."""

    provider: str
    model_id: str


@router.get("/models")
async def list_models() -> dict:
    """Return available models and current per-node assignments."""
    registry = get_llm_registry()
    return {
        "available": registry.list_available(),
        "assignments": registry.get_config(),
    }


@router.put("/models/{node}")
async def update_model(node: str, body: ModelUpdateRequest) -> dict:
    """Change the model for a pipeline node. Takes effect on the next run."""
    registry = get_llm_registry()
    try:
        config = registry.set_model(node, body.provider, body.model_id)
        return {
            "node": node,
            **config.to_dict(),
        }
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/models/reset")
async def reset_models() -> dict:
    """Reset all nodes to their default model assignments."""
    registry = get_llm_registry()
    assignments = registry.reset_defaults()
    return {"assignments": assignments}
