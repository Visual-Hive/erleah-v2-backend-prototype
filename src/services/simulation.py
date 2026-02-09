"""Debug simulation flags for testing failure modes.

Server-side toggle registry. The DevTools GUI sets flags via the debug API,
and pipeline nodes check them at runtime to simulate failures.

This follows the same singleton pattern as prompt_registry and llm_registry.
"""

from __future__ import annotations

import structlog
from typing import TypedDict

logger = structlog.get_logger()


class SimulationFlag(TypedDict):
    """A single simulation flag with metadata."""
    enabled: bool
    description: str
    category: str  # "failure" | "degradation" | "latency" (future)
    affects: list[str]  # Which pipeline nodes are affected


# Default flags — add new ones here as needed
_DEFAULT_FLAGS: dict[str, SimulationFlag] = {
    "simulate_directus_failure": {
        "enabled": False,
        "description": (
            "Forces a ConnectionError in fetch_data. Tests graceful degradation "
            "when user profiles and conversation history are unavailable."
        ),
        "category": "failure",
        "affects": ["fetch_data", "update_profile"],
    },
    "simulate_no_results": {
        "enabled": False,
        "description": (
            "Returns empty results from search queries. Tests the retry loop "
            "and the 'no results found' response path."
        ),
        "category": "failure",
        "affects": ["execute_queries"],
    },
}


class SimulationRegistry:
    """Manages simulation flags for debug/testing.

    Thread-safe singleton — flags persist for the lifetime of the process.
    """

    def __init__(self) -> None:
        # Deep copy defaults so we can reset
        self._flags: dict[str, SimulationFlag] = {
            k: {**v, "affects": list(v["affects"])} for k, v in _DEFAULT_FLAGS.items()
        }

    def get(self, flag_name: str) -> bool:
        """Check if a simulation flag is enabled."""
        flag = self._flags.get(flag_name)
        return flag["enabled"] if flag else False

    def set(self, flag_name: str, enabled: bool) -> SimulationFlag:
        """Enable or disable a simulation flag."""
        if flag_name not in self._flags:
            raise KeyError(f"Unknown simulation flag: {flag_name}")
        self._flags[flag_name]["enabled"] = enabled
        logger.info(
            "simulation.flag_changed",
            flag=flag_name,
            enabled=enabled,
        )
        return self._flags[flag_name]

    def list_all(self) -> dict[str, SimulationFlag]:
        """Return all flags with their current state."""
        return dict(self._flags)

    def active_count(self) -> int:
        """Count of currently enabled flags."""
        return sum(1 for f in self._flags.values() if f["enabled"])

    def reset_all(self) -> dict[str, SimulationFlag]:
        """Reset all flags to disabled."""
        for flag in self._flags.values():
            flag["enabled"] = False
        logger.info("simulation.all_reset")
        return self.list_all()


# Singleton
_registry: SimulationRegistry | None = None


def get_simulation_registry() -> SimulationRegistry:
    """Get the global simulation registry."""
    global _registry
    if _registry is None:
        _registry = SimulationRegistry()
    return _registry
