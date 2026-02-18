"""Tool registry for Phase 3 action tools.

Tools are registered at app startup and looked up by name during
execute_tools node execution.

Usage:
    from src.tools.registry import get_tool, get_tool_descriptions, initialize_tools

    initialize_tools()                      # Call once at startup
    tool = get_tool("lookup_registration")  # Used by execute_tools node
    descs = get_tool_descriptions()         # Injected into plan_queries prompt
"""

from __future__ import annotations

import structlog

from src.tools.action_base import ActionBaseTool

logger = structlog.get_logger()

_TOOLS: dict[str, ActionBaseTool] = {}
_initialized = False


def register_tool(tool: ActionBaseTool) -> None:
    """Register a tool in the global registry."""
    _TOOLS[tool.name] = tool
    logger.info("tool_registry.registered", name=tool.name)


def get_tool(name: str) -> ActionBaseTool | None:
    """Get a tool by name. Returns None if not found."""
    return _TOOLS.get(name)


def get_all_tools() -> dict[str, ActionBaseTool]:
    """Return a copy of all registered tools."""
    return _TOOLS.copy()


def get_tool_descriptions() -> list[dict]:
    """Return tool descriptions formatted for injection into the planner prompt.

    Each dict has: name, description, requires_identifier.
    """
    return [
        {
            "name": tool.name,
            "description": tool.description.strip(),
            "requires_identifier": tool.requires_identifier,
        }
        for tool in _TOOLS.values()
    ]


def initialize_tools() -> None:
    """Register all available action tools. Call once at app startup."""
    global _initialized
    if _initialized:
        return

    from src.tools.registration_lookup import RegistrationLookupTool
    from src.tools.registration_email import SendRegistrationEmailTool

    register_tool(RegistrationLookupTool())
    register_tool(SendRegistrationEmailTool())

    _initialized = True
    logger.info("tool_registry.initialized", count=len(_TOOLS), tools=list(_TOOLS.keys()))
