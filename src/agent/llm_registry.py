"""Runtime-configurable LLM registry.

Allows swapping the model used by each pipeline node at runtime via the
DevTools Model Selector (Phase 3). Replaces hardcoded sonnet/haiku imports
in individual nodes.

Usage in nodes:
    from src.agent.llm_registry import get_llm_registry
    registry = get_llm_registry()
    llm = registry.get_model("plan_queries")
    result = await llm.ainvoke([...])
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import structlog
from langchain_core.language_models.chat_models import BaseChatModel

from src.config import settings

logger = structlog.get_logger()


# ── Model catalogue ──────────────────────────────────────────────────


@dataclass
class ModelOption:
    """A model available for selection."""

    provider: str
    model_id: str
    display_name: str
    speed: str  # "Ultra Fast" | "Very Fast" | "Fast" | "Medium"

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "display_name": self.display_name,
            "speed": self.speed,
        }


AVAILABLE_MODELS: list[ModelOption] = [
    ModelOption("anthropic", "claude-sonnet-4-20250514", "Claude Sonnet 4", "Medium"),
    ModelOption("anthropic", "claude-haiku-4-5-20251001", "Claude Haiku 4.5", "Fast"),
    ModelOption("groq", "llama-3.3-70b-versatile", "Llama 3.3 70B", "Very Fast"),
    ModelOption("groq", "llama-3.1-8b-instant", "Llama 3.1 8B", "Ultra Fast"),
    ModelOption("groq", "mixtral-8x7b-32768", "Mixtral 8x7B", "Very Fast"),
]

# Quick lookup: (provider, model_id) → ModelOption
_MODEL_LOOKUP: dict[tuple[str, str], ModelOption] = {
    (m.provider, m.model_id): m for m in AVAILABLE_MODELS
}

# LLM nodes that the registry manages (generate_acknowledgment uses Grok client separately)
LLM_NODES = ["plan_queries", "generate_response", "evaluate", "update_profile"]

DEFAULT_ASSIGNMENTS: dict[str, tuple[str, str]] = {
    "plan_queries": ("anthropic", "claude-sonnet-4-20250514"),
    "generate_response": ("anthropic", "claude-sonnet-4-20250514"),
    "evaluate": ("anthropic", "claude-haiku-4-5-20251001"),
    "update_profile": ("anthropic", "claude-sonnet-4-20250514"),
}


# ── Model config per node ────────────────────────────────────────────


@dataclass
class ModelConfig:
    """Current model assignment for a single node."""

    provider: str
    model_id: str
    display_name: str
    speed: str
    is_default: bool = True
    _instance: BaseChatModel | None = field(default=None, repr=False)

    def to_dict(self) -> dict:
        return {
            "provider": self.provider,
            "model_id": self.model_id,
            "display_name": self.display_name,
            "speed": self.speed,
            "is_default": self.is_default,
        }


# ── LLM instance factory ─────────────────────────────────────────────


def _create_llm(provider: str, model_id: str) -> BaseChatModel:
    """Create a LangChain chat model instance for a given provider + model."""
    if settings.use_llm_proxy:
        from langchain_openai import ChatOpenAI

        logger.info(
            "  [llm_registry] using local LLM proxy",
            proxy_url=settings.llm_proxy_url,
            model=settings.llm_proxy_model,
        )
        return ChatOpenAI(
            model=settings.llm_proxy_model,
            api_key=settings.llm_proxy_api_key,
            base_url=settings.llm_proxy_url,
            temperature=0,
        )

    if provider == "anthropic":
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(  # type: ignore[call-arg]
            model=model_id,  # type: ignore[call-arg]
            api_key=settings.anthropic_api_key,
            temperature=0,
        )

    if provider == "groq":
        from langchain_groq import ChatGroq  # type: ignore[import-untyped]

        api_key = settings.groq_api_key
        if not api_key:
            raise ValueError("GROQ_API_KEY not set. Add it to .env to use Groq models.")
        return ChatGroq(  # type: ignore[call-arg]
            model=model_id,
            api_key=api_key,
            temperature=0,
        )

    raise ValueError(f"Unknown provider: {provider}")


# ── Registry ──────────────────────────────────────────────────────────


class LLMRegistry:
    """Runtime-configurable model registry. One model per pipeline node."""

    def __init__(self) -> None:
        self._configs: dict[str, ModelConfig] = {}
        self._init_defaults()

    def _init_defaults(self) -> None:
        """Populate with default model assignments (no LLM instances yet — lazy)."""
        for node, (provider, model_id) in DEFAULT_ASSIGNMENTS.items():
            option = _MODEL_LOOKUP[(provider, model_id)]
            self._configs[node] = ModelConfig(
                provider=provider,
                model_id=model_id,
                display_name=option.display_name,
                speed=option.speed,
                is_default=True,
                _instance=None,
            )
        logger.info(
            "  [llm_registry] initialized with defaults",
            nodes=list(self._configs.keys()),
        )

    def get_model(self, node: str) -> BaseChatModel:
        """Get the LLM instance for a given pipeline node. Lazy-creates on first call."""
        config = self._configs.get(node)
        if config is None:
            raise KeyError(f"Unknown node: {node}. Valid nodes: {LLM_NODES}")

        if config._instance is None:
            logger.info(
                "  [llm_registry] creating LLM instance",
                node=node,
                provider=config.provider,
                model=config.model_id,
            )
            config._instance = _create_llm(config.provider, config.model_id)

        return config._instance

    def set_model(self, node: str, provider: str, model_id: str) -> ModelConfig:
        """Change the model for a node. Creates a new LLM instance immediately."""
        if node not in self._configs:
            raise KeyError(f"Unknown node: {node}. Valid nodes: {LLM_NODES}")

        key = (provider, model_id)
        option = _MODEL_LOOKUP.get(key)
        if option is None:
            valid = [(m.provider, m.model_id) for m in AVAILABLE_MODELS]
            raise ValueError(
                f"Unknown model: {provider}/{model_id}. Available: {valid}"
            )

        # Check if this is the default assignment
        default = DEFAULT_ASSIGNMENTS[node]
        is_default = (provider, model_id) == default

        # Create a new instance eagerly so errors surface immediately
        instance = _create_llm(provider, model_id)

        self._configs[node] = ModelConfig(
            provider=provider,
            model_id=model_id,
            display_name=option.display_name,
            speed=option.speed,
            is_default=is_default,
            _instance=instance,
        )

        logger.info(
            "  [llm_registry] model changed",
            node=node,
            provider=provider,
            model=model_id,
            is_default=is_default,
        )
        return self._configs[node]

    def get_node_config(self, node: str) -> ModelConfig:
        """Return the current ModelConfig for a node."""
        config = self._configs.get(node)
        if config is None:
            raise KeyError(f"Unknown node: {node}")
        return config

    def list_available(self) -> list[dict]:
        """Return all available models across providers."""
        result = []
        for m in AVAILABLE_MODELS:
            entry = m.to_dict()
            # Mark Groq models as unavailable if no API key
            if m.provider == "groq" and not settings.groq_api_key:
                entry["available"] = False
                entry["reason"] = "GROQ_API_KEY not configured"
            else:
                entry["available"] = True
            result.append(entry)
        return result

    def get_config(self) -> dict[str, dict]:
        """Return current model assignments per node."""
        return {node: cfg.to_dict() for node, cfg in self._configs.items()}

    def reset_defaults(self) -> dict[str, dict]:
        """Reset all nodes to their default model assignments."""
        self._configs.clear()
        self._init_defaults()
        logger.info("  [llm_registry] reset all to defaults")
        return self.get_config()

    def non_default_count(self) -> int:
        """Return the number of nodes using a non-default model."""
        return sum(1 for cfg in self._configs.values() if not cfg.is_default)


# ── Singleton ─────────────────────────────────────────────────────────

_registry: LLMRegistry | None = None


def get_llm_registry() -> LLMRegistry:
    """Get the singleton LLM registry instance."""
    global _registry
    if _registry is None:
        _registry = LLMRegistry()
    return _registry
