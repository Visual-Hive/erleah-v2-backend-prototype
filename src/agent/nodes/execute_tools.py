"""Node: execute_tools — runs Phase 3 action tool calls from the planner.

Triggered when plan_queries outputs tool_calls (registration, email, etc.)
instead of (or in addition to) search queries.

Flow:
  plan_queries → [tool_calls present?] → execute_tools → generate_response

Tool calls are executed sequentially. The output of earlier tools (e.g.
lookup_registration → internal_id) is automatically injected into the
args of later tools that need it (e.g. send_registration_email → internal_id).
"""

import structlog

from src.agent.state import AssistantState
from src.tools.registry import get_tool

logger = structlog.get_logger()


async def execute_tools(state: AssistantState) -> dict:
    """Execute tool calls produced by the planner.

    Each tool in tool_calls runs in sequence. The result of
    lookup_registration is automatically forwarded to send_registration_email
    so the planner doesn't need to know the internal_id in advance.
    """
    logger.info("===== NODE: EXECUTE TOOLS =====")
    tool_calls: list[dict] = state.get("tool_calls") or []

    if not tool_calls:
        logger.info("  [execute_tools] no tool_calls, skipping")
        return {"tool_results": {}, "current_node": "execute_tools"}

    context = {
        "trace_id": state.get("trace_id", ""),
        "conversation_id": (state.get("conversation_context") or {}).get(
            "conversation_id", ""
        ),
        "conference_id": (state.get("user_context") or {}).get("conference_id", ""),
    }

    results: dict[str, dict] = {}
    lookup_result: dict | None = None  # Cached lookup data for downstream tools

    for call in tool_calls:
        tool_name: str = call.get("tool", "")
        tool_args: dict = dict(call.get("args") or {})

        tool = get_tool(tool_name)
        if not tool:
            logger.warning("  [execute_tools] unknown tool", name=tool_name)
            results[tool_name] = {
                "success": False,
                "error": f"Unknown tool: {tool_name}",
                "data": None,
                "user_message": None,
            }
            continue

        # Auto-inject internal_id from lookup result into send tool args
        if tool_name == "send_registration_email" and lookup_result:
            if "internal_id" not in tool_args or not tool_args["internal_id"]:
                internal_id = (lookup_result.get("data") or {}).get("internal_id")
                if internal_id:
                    tool_args["internal_id"] = internal_id
                    logger.info(
                        "  [execute_tools] injected internal_id from lookup",
                        tool=tool_name,
                    )

        logger.info(
            "  [execute_tools] running tool",
            name=tool_name,
            reason=call.get("reason", ""),
        )
        result = await tool.safe_execute(tool_args, context)
        results[tool_name] = result

        # Cache lookup result for downstream injection
        if tool_name == "lookup_registration" and result.get("success"):
            lookup_result = result

        logger.info(
            "  [execute_tools] tool complete",
            name=tool_name,
            success=result.get("success"),
        )

    logger.info(
        "===== NODE: EXECUTE TOOLS COMPLETE =====",
        tools_run=list(results.keys()),
        all_succeeded=all(r.get("success") for r in results.values()),
    )

    return {
        "tool_results": results,
        "current_node": "execute_tools",
    }
