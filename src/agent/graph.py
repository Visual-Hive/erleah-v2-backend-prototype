"""
9-node LangGraph pipeline for the Erleah conference assistant.

Flow:
  START → fetch_data_parallel
    → [conditional: profile_needs_update?] → update_profile (or skip)
    → generate_acknowledgment
    → plan_queries
    → execute_queries
    → check_results
    → [conditional: needs_retry?] → relax_and_retry → check_results (loop)
    → generate_response (streaming tokens forwarded via SSE)
    → evaluate (non-blocking, runs after 'done' is sent)
    → END
"""

import asyncio
import json
import time
from typing import AsyncGenerator

import structlog
from langchain_core.messages import HumanMessage
from langgraph.graph import END, StateGraph

from src.agent.nodes.check_results import check_results
from src.agent.nodes.evaluate import evaluate
from src.agent.nodes.execute_queries import execute_queries
from src.agent.nodes.fetch_data import fetch_data_parallel
from src.agent.nodes.generate_acknowledgment import generate_acknowledgment
from src.agent.nodes.generate_response import generate_response
from src.agent.nodes.plan_queries import plan_queries
from src.agent.nodes.relax_and_retry import relax_and_retry
from src.agent.nodes.update_profile import update_profile
from src.agent.prompt_registry import get_prompt_registry
from src.agent.state import AssistantState
from src.middleware.logging import trace_id_var
from src.monitoring.metrics import (
    LLM_TOKENS,
    LLM_DURATION,
    LLM_CALLS,
    ERRORS,
    TIME_TO_FIRST_FEEDBACK,
    TIME_TO_FIRST_CHUNK,
    USER_ABANDONED,
)
from src.config import settings
from src.services.cache import get_cache_service
from src.services.errors import WorkflowTimeout, get_user_error

logger = structlog.get_logger()

WORKFLOW_TIMEOUT = 30.0  # seconds


# --- Conditional edges ---


def should_update_profile(state: AssistantState) -> str:
    """Route to update_profile if the message contains profile info."""
    needs_update = state.get("profile_needs_update", False)
    decision = "update_profile" if needs_update else "generate_acknowledgment"
    logger.info(
        "  [conditional] should_update_profile?",
        needs_update=needs_update,
        decision=decision,
    )
    return decision


def should_retry(state: AssistantState) -> str:
    """Route to relax_and_retry if there are zero-result tables and retries left."""
    needs_retry = state.get("needs_retry", False)
    retry_count = state.get("retry_count", 0)
    zero_tables = state.get("zero_result_tables", [])
    decision = "relax_and_retry" if needs_retry else "generate_response"
    logger.info(
        "  [conditional] should_retry?",
        needs_retry=needs_retry,
        retry_count=retry_count,
        zero_result_tables=zero_tables,
        decision=decision,
    )
    return decision


# --- Build the graph ---

graph_builder = StateGraph(AssistantState)

# Add nodes
graph_builder.add_node("fetch_data", fetch_data_parallel)
graph_builder.add_node("update_profile", update_profile)
graph_builder.add_node("generate_acknowledgment", generate_acknowledgment)
graph_builder.add_node("plan_queries", plan_queries)
graph_builder.add_node("execute_queries", execute_queries)
graph_builder.add_node("check_results", check_results)
graph_builder.add_node("relax_and_retry", relax_and_retry)
graph_builder.add_node("generate_response", generate_response)
graph_builder.add_node("evaluate", evaluate)

# Wire edges
graph_builder.set_entry_point("fetch_data")

# fetch_data → conditional → update_profile OR generate_acknowledgment
graph_builder.add_conditional_edges(
    "fetch_data",
    should_update_profile,
    {
        "update_profile": "update_profile",
        "generate_acknowledgment": "generate_acknowledgment",
    },
)

# update_profile → generate_acknowledgment
graph_builder.add_edge("update_profile", "generate_acknowledgment")

# generate_acknowledgment → plan_queries
graph_builder.add_edge("generate_acknowledgment", "plan_queries")

# plan_queries → execute_queries
graph_builder.add_edge("plan_queries", "execute_queries")

# execute_queries → check_results
graph_builder.add_edge("execute_queries", "check_results")

# check_results → conditional → relax_and_retry OR generate_response
graph_builder.add_conditional_edges(
    "check_results",
    should_retry,
    {"relax_and_retry": "relax_and_retry", "generate_response": "generate_response"},
)

# relax_and_retry → check_results (loop back)
graph_builder.add_edge("relax_and_retry", "check_results")

# generate_response → evaluate
graph_builder.add_edge("generate_response", "evaluate")

# evaluate → END
graph_builder.add_edge("evaluate", END)

# Compile
graph = graph_builder.compile()


# --- Progress messages for user-friendly UX ---

PROGRESS_MESSAGES = {
    "fetch_data": "Loading your profile...",
    "update_profile": "Updating your profile...",
    "generate_acknowledgment": None,  # Handled separately
    "plan_queries": "Planning search strategy...",
    "execute_queries": "Searching databases...",
    "check_results": "Analyzing results...",
    "relax_and_retry": "No exact matches found. Expanding search...",
    "generate_response": "Preparing recommendations...",
    "evaluate": None,  # Runs after done
}


def _track_llm_usage(event: dict) -> None:
    """Extract and record LLM token usage from astream_events."""
    if event["event"] != "on_chat_model_end":
        return
    output = event.get("data", {}).get("output")
    if not output:
        return

    usage = getattr(output, "usage_metadata", None)
    if not usage:
        # Try response_metadata
        resp_meta = getattr(output, "response_metadata", None)
        if resp_meta:
            usage = resp_meta.get("usage")

    if not usage:
        return

    # Determine model from event
    metadata = event.get("metadata", {})
    node = metadata.get("langgraph_node", "unknown")
    model = "unknown"
    if hasattr(output, "response_metadata"):
        resp = output.response_metadata
        model = (
            resp.get("model", "")
            or resp.get("model_name", "")
            or resp.get("model_id", "")
            or "unknown"
        )
    # Fallback: try to get model from the event tags or metadata
    if model == "unknown":
        tags = event.get("tags", [])
        for tag in tags:
            if "claude" in tag or "sonnet" in tag or "haiku" in tag:
                model = tag
                break
    if model == "unknown":
        # Last resort: infer from node
        if node in ("plan_queries", "generate_response", "update_profile"):
            model = "claude-sonnet"
        elif node == "evaluate":
            model = "claude-haiku"

    # Extract token counts (LangChain usage_metadata format)
    if isinstance(usage, dict):
        input_tokens = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
        output_tokens = usage.get("output_tokens", 0) or usage.get(
            "completion_tokens", 0
        )
        cached_tokens = usage.get("cache_read_input_tokens", 0) or usage.get(
            "cache_creation_input_tokens", 0
        )
    else:
        input_tokens = getattr(usage, "input_tokens", 0) or getattr(
            usage, "prompt_tokens", 0
        )
        output_tokens = getattr(usage, "output_tokens", 0) or getattr(
            usage, "completion_tokens", 0
        )
        cached_tokens = getattr(usage, "cache_read_input_tokens", 0)

    # Log LLM usage for demo visibility
    logger.info(
        "  [llm_usage] LLM call completed",
        model=model,
        node=node,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cached_tokens=cached_tokens,
    )

    if input_tokens:
        LLM_TOKENS.labels(model=model, token_type="input").inc(input_tokens)
    if output_tokens:
        LLM_TOKENS.labels(model=model, token_type="output").inc(output_tokens)
    if cached_tokens:
        LLM_TOKENS.labels(model=model, token_type="cached").inc(cached_tokens)

    LLM_CALLS.labels(model=model, node=node).inc()

    # Return extracted data for debug events
    return {
        "node": node,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
    }


# --- Debug helpers ---

# Pipeline nodes we track for debug (excludes internal LangGraph routing)
_PIPELINE_NODES = {
    "fetch_data", "update_profile", "generate_acknowledgment",
    "plan_queries", "execute_queries", "check_results",
    "relax_and_retry", "generate_response", "evaluate",
}

# Nodes that call an LLM
_LLM_NODES = {
    "plan_queries", "generate_response", "evaluate",
    "update_profile", "generate_acknowledgment",
}

# Mapping from pipeline node → prompt registry key(s)
_NODE_PROMPT_KEYS: dict[str, str] = {
    "plan_queries": "plan_queries",
    "generate_response": "generate_response",
    "evaluate": "evaluate",
    "update_profile": "profile_update",
    "generate_acknowledgment": "acknowledgment",
}


def _sanitize_for_debug(data: dict | None, max_str_len: int = 500) -> dict:
    """Create a JSON-safe, size-limited snapshot of state data for debug events."""
    if not data or not isinstance(data, dict):
        return {}
    result = {}
    # Skip large/internal fields
    skip_keys = {"messages", "progress_updates"}
    for key, value in data.items():
        if key in skip_keys:
            continue
        try:
            # Truncate long strings
            if isinstance(value, str) and len(value) > max_str_len:
                result[key] = value[:max_str_len] + "..."
            elif isinstance(value, list) and len(value) > 20:
                result[key] = value[:20]
                result[f"{key}_count"] = len(value)
            elif isinstance(value, dict) and len(str(value)) > 2000:
                result[key] = {k: "..." for k in list(value.keys())[:10]}
            else:
                # Quick JSON-serializable check
                json.dumps(value)
                result[key] = value
        except (TypeError, ValueError):
            result[key] = str(value)[:max_str_len]
    return result


async def stream_agent_response(
    message: str, user_context: dict
) -> AsyncGenerator[dict, None]:
    """Stream agent responses as SSE events with 30s timeout.

    Event types:
    - acknowledgment: contextual acknowledgment from Grok node
    - progress: sent when each node starts (node name + user-friendly message)
    - chunk: streamed response tokens (only from generate_response node)
    - done: sent after generate_response completes (includes trace_id + referenced_ids)
    - error: sent on failures
    """
    request_start = time.perf_counter()
    first_feedback_sent = False
    first_chunk_sent = False

    trace_id = trace_id_var.get("")

    logger.info(
        "========== PIPELINE START ==========",
        trace_id=trace_id,
        message=message[:200],
        user_context=user_context,
        timeout=f"{WORKFLOW_TIMEOUT}s",
    )
    logger.info(
        "  Pipeline flow: fetch_data -> [update_profile?] -> acknowledgment -> plan_queries "
        "-> execute_queries -> check_results -> [retry?] -> generate_response -> evaluate -> END"
    )

    initial_state: AssistantState = {
        "messages": [HumanMessage(content=message)],
        "user_context": user_context,
        "user_profile": {},
        "conversation_history": [],
        "profile_needs_update": False,
        "profile_updates": None,
        "profile_updated": False,
        "intent": "",
        "query_mode": None,
        "planned_queries": [],
        "query_results": {},
        "zero_result_tables": [],
        "retry_count": 0,
        "needs_retry": False,
        "retry_metadata": None,
        "response_text": "",
        "referenced_ids": [],
        "progress_updates": [],
        "quality_score": None,
        "confidence_score": None,
        "evaluation": None,
        "acknowledgment_text": "",
        "trace_id": trace_id,
        "started_at": time.time(),
        "completed_at": None,
        "error": None,
        "error_node": None,
        "current_node": "",
    }

    seen_nodes: set[str] = set()
    done_sent = False
    ack_sent = False
    chunk_count = 0
    referenced_ids: list[str] = []

    # Debug tracking (only used when debug_mode is on)
    debug = settings.debug_mode
    node_start_times: dict[str, float] = {}  # node → perf_counter timestamp
    node_llm_usage: dict[str, dict] = {}     # node → {model, input_tokens, ...}
    node_last_output: dict[str, dict] = {}   # node → latest raw output from on_chain_end
    node_ended: set[str] = set()             # nodes for which we've emitted node_end
    completed_nodes: list[dict] = []         # ordered list for pipeline_summary
    current_debug_node: str | None = None    # the currently active node

    # Publish progress to Redis for multi-instance visibility
    cache = get_cache_service()

    try:
        async for event in _stream_with_timeout(initial_state):
            kind = event["event"]
            metadata = event.get("metadata", {})
            langgraph_node = metadata.get("langgraph_node", "")

            # Track LLM token usage (+ capture for debug)
            llm_info = _track_llm_usage(event)  # type: ignore[arg-type]
            if debug and llm_info and llm_info["node"] in _PIPELINE_NODES:
                node_llm_usage[llm_info["node"]] = llm_info

            # Send progress events when a new node starts
            if langgraph_node and langgraph_node not in seen_nodes:
                seen_nodes.add(langgraph_node)
                progress_msg = PROGRESS_MESSAGES.get(langgraph_node)
                elapsed = time.perf_counter() - request_start

                # Record start time for debug duration tracking
                if debug and langgraph_node in _PIPELINE_NODES:
                    node_start_times[langgraph_node] = time.perf_counter()

                logger.info(
                    "  [sse] progress event",
                    node=langgraph_node,
                    message=progress_msg,
                    elapsed=f"{elapsed:.2f}s",
                    nodes_seen=list(seen_nodes),
                )

                if not first_feedback_sent:
                    first_feedback_sent = True
                    TIME_TO_FIRST_FEEDBACK.observe(elapsed)
                    logger.info(
                        "  [sse] first feedback sent",
                        time_to_first_feedback=f"{elapsed:.3f}s",
                    )

                yield {
                    "event": "progress",
                    "data": {"node": langgraph_node, "message": progress_msg},
                }

                # Debug: emit node_end for the PREVIOUS node (it just finished)
                if debug and current_debug_node and current_debug_node not in node_ended:
                    prev = current_debug_node
                    node_ended.add(prev)
                    now = time.perf_counter()
                    duration_ms = round((now - node_start_times.get(prev, now)) * 1000)
                    output = node_last_output.get(prev, {})

                    node_end_data: dict = {
                        "node": prev,
                        "ts": time.time(),
                        "duration_ms": duration_ms,
                        "output": output,
                    }
                    # Include prompt version for LLM nodes
                    prompt_key = _NODE_PROMPT_KEYS.get(prev)
                    if prompt_key:
                        try:
                            registry = get_prompt_registry()
                            node_end_data["prompt_version"] = registry.get_version(prompt_key)
                        except Exception:
                            pass
                    if prev in node_llm_usage:
                        llm = node_llm_usage[prev]
                        node_end_data["llm"] = {
                            "model": llm["model"],
                            "input_tokens": llm["input_tokens"],
                            "output_tokens": llm["output_tokens"],
                            "cached_tokens": llm["cached_tokens"],
                        }
                    summary_entry: dict = {"node": prev, "duration_ms": duration_ms, "status": "ok"}
                    if prev in node_llm_usage:
                        summary_entry["model"] = node_llm_usage[prev]["model"]
                    completed_nodes.append(summary_entry)

                    logger.info("  [debug] node_end", node=prev, duration_ms=duration_ms)
                    yield {"event": "node_end", "data": node_end_data}

                # Track current debug node
                if debug and langgraph_node in _PIPELINE_NODES:
                    current_debug_node = langgraph_node

                # Emit debug node_start event
                if debug and langgraph_node in _PIPELINE_NODES:
                    yield {
                        "event": "node_start",
                        "data": {
                            "node": langgraph_node,
                            "ts": time.time(),
                        },
                    }

                # Publish to Redis pub/sub
                await cache.publish(
                    f"progress:{trace_id}",
                    json.dumps({"node": langgraph_node, "message": progress_msg}),
                )

            # Send contextual acknowledgment when generate_acknowledgment finishes
            if (
                kind == "on_chain_end"
                and langgraph_node == "generate_acknowledgment"
                and not ack_sent
            ):
                ack_sent = True
                output = event.get("data", {}).get("output", {})
                ack_text = (
                    output.get("acknowledgment_text", "")
                    if isinstance(output, dict)
                    else ""
                )
                if ack_text:
                    logger.info(
                        "  [sse] acknowledgment event",
                        text=ack_text[:100],
                        elapsed=f"{time.perf_counter() - request_start:.2f}s",
                    )
                    yield {
                        "event": "acknowledgment",
                        "data": {"message": ack_text},
                    }
                else:
                    logger.info("  [sse] acknowledgment skipped (empty text)")

            # Capture referenced_ids when generate_response finishes
            if kind == "on_chain_end" and langgraph_node == "generate_response":
                output = event.get("data", {}).get("output", {})
                if isinstance(output, dict):
                    referenced_ids = output.get("referenced_ids", [])

            # Stream tokens only from generate_response node
            if kind == "on_chat_model_stream" and langgraph_node == "generate_response":
                chunk = event["data"].get("chunk")
                if chunk and chunk.content:
                    content = chunk.content
                    if isinstance(content, list):
                        for block in content:
                            if isinstance(block, dict) and block.get("type") == "text":
                                text = block.get("text", "")
                                if text:
                                    chunk_count += 1
                                    if not first_chunk_sent:
                                        first_chunk_sent = True
                                        ttfc = time.perf_counter() - request_start
                                        TIME_TO_FIRST_CHUNK.observe(ttfc)
                                        logger.info(
                                            "  [sse] first chunk sent",
                                            time_to_first_chunk=f"{ttfc:.3f}s",
                                        )
                                    yield {"event": "chunk", "data": {"text": text}}
                    elif isinstance(content, str):
                        chunk_count += 1
                        if not first_chunk_sent:
                            first_chunk_sent = True
                            ttfc = time.perf_counter() - request_start
                            TIME_TO_FIRST_CHUNK.observe(ttfc)
                            logger.info(
                                "  [sse] first chunk sent",
                                time_to_first_chunk=f"{ttfc:.3f}s",
                            )
                        yield {"event": "chunk", "data": {"text": content}}

            # Detect when generate_response finishes → send done before evaluate
            if (
                kind == "on_chain_end"
                and langgraph_node == "generate_response"
                and not done_sent
            ):
                done_sent = True
                elapsed = time.perf_counter() - request_start
                logger.info(
                    "  [sse] done event — response complete",
                    chunks_streamed=chunk_count,
                    referenced_ids_count=len(referenced_ids),
                    elapsed=f"{elapsed:.2f}s",
                )
                yield {
                    "event": "done",
                    "data": {
                        "trace_id": trace_id,
                        "referenced_ids": referenced_ids,
                    },
                }

            # --- Debug: capture latest output from on_chain_end ---
            if (
                debug
                and kind == "on_chain_end"
                and langgraph_node in _PIPELINE_NODES
            ):
                output = event.get("data", {}).get("output", {})
                if isinstance(output, dict) and output:
                    sanitized = _sanitize_for_debug(output)
                    if sanitized:
                        node_last_output[langgraph_node] = sanitized

    except asyncio.TimeoutError:
        elapsed = time.perf_counter() - request_start
        logger.error(
            "  [pipeline] TIMEOUT — workflow exceeded deadline",
            timeout=f"{WORKFLOW_TIMEOUT}s",
            elapsed=f"{elapsed:.2f}s",
            nodes_completed=list(seen_nodes),
        )
        ERRORS.labels(error_type="WorkflowTimeout", node="pipeline").inc()
        error_info = get_user_error(WorkflowTimeout())
        yield {"event": "error", "data": error_info}
    except Exception as e:
        elapsed = time.perf_counter() - request_start
        logger.error(
            "  [pipeline] ERROR — unhandled exception",
            error_type=type(e).__name__,
            error=str(e),
            elapsed=f"{elapsed:.2f}s",
            nodes_completed=list(seen_nodes),
        )
        ERRORS.labels(error_type=type(e).__name__, node="pipeline").inc()
        error_info = get_user_error(e)
        yield {"event": "error", "data": error_info}

    # Fallback: if done was never sent (e.g. error path), send it now
    if not done_sent:
        logger.info("  [sse] fallback done event (error path)")
        yield {
            "event": "done",
            "data": {
                "trace_id": trace_id,
                "referenced_ids": referenced_ids,
            },
        }

    # Pipeline completion summary
    total_elapsed = time.perf_counter() - request_start
    logger.info(
        "========== PIPELINE COMPLETE ==========",
        trace_id=trace_id,
        total_duration=f"{total_elapsed:.2f}s",
        nodes_visited=list(seen_nodes),
        chunks_streamed=chunk_count,
        referenced_ids=len(referenced_ids),
        had_error=not done_sent,
    )

    # Debug: emit node_end for the LAST node (no next node to trigger transition)
    if debug and current_debug_node and current_debug_node not in node_ended:
        prev = current_debug_node
        node_ended.add(prev)
        now = time.perf_counter()
        duration_ms = round((now - node_start_times.get(prev, now)) * 1000)
        output = node_last_output.get(prev, {})

        node_end_data = {
            "node": prev,
            "ts": time.time(),
            "duration_ms": duration_ms,
            "output": output,
        }
        # Include prompt version for LLM nodes
        prompt_key = _NODE_PROMPT_KEYS.get(prev)
        if prompt_key:
            try:
                registry = get_prompt_registry()
                node_end_data["prompt_version"] = registry.get_version(prompt_key)
            except Exception:
                pass
        if prev in node_llm_usage:
            llm = node_llm_usage[prev]
            node_end_data["llm"] = {
                "model": llm["model"],
                "input_tokens": llm["input_tokens"],
                "output_tokens": llm["output_tokens"],
                "cached_tokens": llm["cached_tokens"],
            }
        summary_entry = {"node": prev, "duration_ms": duration_ms, "status": "ok"}
        if prev in node_llm_usage:
            summary_entry["model"] = node_llm_usage[prev]["model"]
        completed_nodes.append(summary_entry)

        logger.info("  [debug] node_end (final)", node=prev, duration_ms=duration_ms)
        yield {"event": "node_end", "data": node_end_data}

    # Debug: emit pipeline_summary
    if debug and completed_nodes:
        total_tokens = {"input": 0, "output": 0, "cached": 0}
        for llm in node_llm_usage.values():
            total_tokens["input"] += llm.get("input_tokens", 0)
            total_tokens["output"] += llm.get("output_tokens", 0)
            total_tokens["cached"] += llm.get("cached_tokens", 0)

        yield {
            "event": "pipeline_summary",
            "data": {
                "trace_id": trace_id,
                "total_ms": round(total_elapsed * 1000),
                "nodes": completed_nodes,
                "total_tokens": total_tokens,
            },
        }


async def _stream_with_timeout(initial_state: AssistantState):
    """Wrap graph.astream_events with a 30s workflow timeout."""
    deadline = time.monotonic() + WORKFLOW_TIMEOUT

    async for event in graph.astream_events(initial_state, version="v2"):
        if time.monotonic() > deadline:
            raise asyncio.TimeoutError("Workflow exceeded 30s timeout")
        yield event
