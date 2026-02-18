"""Base class for Phase 3 action tools.

Action tools are different from search tools (ErleahBaseTool / LangChain):
- They perform side-effects (look up data, send emails, etc.)
- They're invoked by the planner when specific intents are detected
- They run in the execute_tools node, not execute_queries
- They use a simpler execute(args, context) interface

Security contract:
- execute() MUST never return private data (email addresses, full names, etc.)
- safe_execute() wraps execute() — never raises, always returns a result dict
- Tools log trace_id on every call but NEVER log PII (identifiers, emails)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import structlog

logger = structlog.get_logger()


class ActionBaseTool(ABC):
    """Base class for all Phase 3 action tools.

    Subclasses implement execute(args, context) and declare:
      name: str            — unique tool name, used by the planner
      description: str     — used by the planner to decide when to invoke
      requires_identifier  — whether user must provide email/reg ID first
      returns_private_data — whether this tool handles private data internally
      rate_limit_key       — which rate limit bucket to use (if any)
    """

    name: str = ""
    description: str = ""
    requires_identifier: bool = False
    returns_private_data: bool = False
    rate_limit_key: str | None = None

    @abstractmethod
    async def execute(self, args: dict[str, Any], context: dict) -> dict[str, Any]:
        """Execute the tool.

        Args:
            args:    Tool-specific arguments (from planner output)
            context: Pipeline context — trace_id, conversation_id, conference_id, etc.

        Returns a dict always containing:
            success:      bool
            data:         dict | None  — safe data for the agent to use
            error:        str | None   — error message (no PII)
            user_message: str | None   — suggested message for the agent to relay
                                         (set when the tool wants to guide the response)
        """
        ...

    async def safe_execute(
        self, args: dict[str, Any], context: dict
    ) -> dict[str, Any]:
        """Execute with error handling — never raises, always returns a result dict.

        Called by execute_tools node. Logs tool name + trace ID but never args
        (which may contain PII like email addresses).
        """
        trace_id = context.get("trace_id", "")
        try:
            logger.info(
                "action_tool.start",
                tool=self.name,
                trace_id=trace_id,
                # args deliberately omitted — may contain email / reg ID
            )
            result = await self.execute(args, context)
            logger.info(
                "action_tool.done",
                tool=self.name,
                success=result.get("success"),
                trace_id=trace_id,
            )
            # Ensure result always has required keys
            result.setdefault("success", True)
            result.setdefault("data", None)
            result.setdefault("error", None)
            result.setdefault("user_message", None)
            return result
        except Exception as e:
            logger.error(
                "action_tool.error",
                tool=self.name,
                error=str(e),
                trace_id=trace_id,
            )
            return {
                "success": False,
                "data": None,
                "error": f"Tool '{self.name}' encountered an error: {type(e).__name__}",
                "user_message": (
                    "I ran into a problem processing that request. "
                    "Could you try again in a moment?"
                ),
            }
