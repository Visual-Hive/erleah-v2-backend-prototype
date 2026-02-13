"""Runtime-mutable prompt store for the Erleah pipeline.

Initialized from defaults in prompts.py and grok.py.
Supports hot-reload via the debug API — changes take effect on the next pipeline run.
"""

import time
from dataclasses import dataclass, field
from typing import Any

import structlog

from src.agent.prompts import (
    ACKNOWLEDGMENT_SYSTEM,
    EVALUATE_SYSTEM,
    GENERATE_RESPONSE_SYSTEM,
    PLAN_QUERIES_SYSTEM,
    PROFILE_DETECT_SYSTEM,
    PROFILE_UPDATE_SYSTEM,
)

logger = structlog.get_logger()


@dataclass
class PromptConfig:
    """Metadata wrapper around a prompt text."""

    text: str
    default_text: str
    version: int = 1
    updated_at: float = field(default_factory=time.time)
    node: str = ""

    @property
    def is_default(self) -> bool:
        return self.text == self.default_text

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "version": self.version,
            "updated_at": self.updated_at,
            "is_default": self.is_default,
            "node": self.node,
        }


# Mapping of prompt key → (default text, associated node)
_PROMPT_DEFAULTS: dict[str, tuple[str, str]] = {
    "plan_queries": (PLAN_QUERIES_SYSTEM, "plan_queries"),
    "generate_response": (GENERATE_RESPONSE_SYSTEM, "generate_response"),
    "evaluate": (EVALUATE_SYSTEM, "evaluate"),
    "profile_detect": (PROFILE_DETECT_SYSTEM, "update_profile"),
    "profile_update": (PROFILE_UPDATE_SYSTEM, "update_profile"),
    "acknowledgment": (ACKNOWLEDGMENT_SYSTEM, "generate_acknowledgment"),
}


class PromptRegistry:
    """Runtime-mutable prompt store."""

    def __init__(self) -> None:
        self._prompts: dict[str, PromptConfig] = {}
        self._init_defaults()

    def _init_defaults(self) -> None:
        """Load all prompts from their default sources."""
        for key, (default_text, node) in _PROMPT_DEFAULTS.items():
            self._prompts[key] = PromptConfig(
                text=default_text,
                default_text=default_text,
                node=node,
            )
        logger.info(
            "prompt_registry.initialized",
            prompt_count=len(self._prompts),
            keys=list(self._prompts.keys()),
        )

    def get(self, key: str) -> str:
        """Get current prompt text for a key. Raises KeyError if unknown."""
        config = self._prompts.get(key)
        if config is None:
            raise KeyError(f"Unknown prompt key: {key}")
        return config.text

    def get_config(self, key: str) -> PromptConfig:
        """Get full config for a key. Raises KeyError if unknown."""
        config = self._prompts.get(key)
        if config is None:
            raise KeyError(f"Unknown prompt key: {key}")
        return config

    def get_version(self, key: str) -> int:
        """Get current version number for a key."""
        config = self._prompts.get(key)
        return config.version if config else 0

    def update(self, key: str, text: str) -> PromptConfig:
        """Update prompt text, bump version, return new config."""
        config = self._prompts.get(key)
        if config is None:
            raise KeyError(f"Unknown prompt key: {key}")
        config.text = text
        config.version += 1
        config.updated_at = time.time()
        logger.info(
            "prompt_registry.updated",
            key=key,
            version=config.version,
            is_default=config.is_default,
            text_length=len(text),
        )
        return config

    def reset(self, key: str) -> PromptConfig:
        """Reset prompt to its default text, bump version."""
        config = self._prompts.get(key)
        if config is None:
            raise KeyError(f"Unknown prompt key: {key}")
        config.text = config.default_text
        config.version += 1
        config.updated_at = time.time()
        logger.info(
            "prompt_registry.reset",
            key=key,
            version=config.version,
        )
        return config

    def list_all(self) -> dict[str, dict]:
        """Return all prompts with metadata."""
        return {key: config.to_dict() for key, config in self._prompts.items()}

    def keys(self) -> list[str]:
        """Return all registered prompt keys."""
        return list(self._prompts.keys())


# ── Singleton ──

_registry: PromptRegistry | None = None


def get_prompt_registry() -> PromptRegistry:
    """Get or create the global prompt registry singleton."""
    global _registry
    if _registry is None:
        _registry = PromptRegistry()
    return _registry
