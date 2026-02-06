"""
Base tool class for all Erleah tools.

Provides common functionality for error handling, logging, etc.
"""

from abc import ABC, abstractmethod
from typing import Any

from langchain.tools import BaseTool as LangChainBaseTool


class ErleahBaseTool(LangChainBaseTool, ABC):
    """Base class for all Erleah tools.

    Extends LangChain's BaseTool with Erleah-specific functionality.
    """

    # Tool metadata (override in subclasses)
    name: str = ""
    description: str = ""

    def _run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Synchronous tool execution (not used - we use async).

        Raises:
            NotImplementedError: Always use _arun instead
        """
        raise NotImplementedError("Use async version (_arun) instead")

    @abstractmethod
    async def _arun(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Async tool execution (implement in subclasses).

        Args:
            *args: Positional arguments
            **kwargs: Keyword arguments

        Returns:
            Dictionary with tool results. Should always include:
            - success: bool (whether tool succeeded)
            - data: any (the actual result)
            - error: str | None (error message if failed)
        """
        pass

    def _handle_error(self, error: Exception) -> dict[str, Any]:
        """Standard error handling for tools.

        Args:
            error: The exception that occurred

        Returns:
            Error result dictionary
        """
        return {
            "success": False,
            "data": None,
            "error": str(error),
            "error_type": type(error).__name__,
        }

    async def _safe_run(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Run tool with error handling.

        This wraps _arun with try/except to ensure errors are returned
        as data rather than raised (agent can handle errors better this way).

        Returns:
            Result dictionary, always with success/data/error fields
        """
        try:
            result = await self._arun(*args, **kwargs)

            # Ensure result has required fields
            if not isinstance(result, dict):
                return {"data": result, "success": True, "error": None}

            if "success" not in result:
                result["success"] = True  # type: ignore[literal-required]

            if "error" not in result:
                result["error"] = None  # type: ignore[literal-required]

            return result

        except Exception as e:
            return self._handle_error(e)
