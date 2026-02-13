"""
9-node LangGraph pipeline for the Erleah conference assistant.

Flow:
  START → fetch_data_parallel (I/O only)
    → generate_acknowledgment
    → plan_queries (LLM: Planning + Profile Update Detection)
    → [conditional: profile_needs_update?] → update_profile (or skip)
    → [conditional: direct_response?] → generate_response (bypass search)
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
from src.agent.llm_registry import get_llm_registry
from src.agent.prompt_registry import get_prompt_registry
from src.agent.state import AssistantState
from src.services.directus_streaming import DirectusMessageWriter
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

WORKFLOW_TIMEOUT = 120.0  # seconds (increased for Proxy/Gemini latency)


# --- Conditional edges ---


def should_update_profile(state: AssistantState) -> str:
    """Route to update_profile if the message contains profile info.

    Also checks force_response — if a critical failure occurred, skip
    straight to generate_response regardless of profile needs.
    """
    if state.get("force_response"):
        logger.info("  [conditional] force_response=True, skipping to generate_response")
        return "generate_response"
    needs_update = state.get("profile_needs_update", False)
    direct = state.get("direct_response", False)

    # If we need update, go to update_profile
    if needs_update:
        logger.info("  [conditional] should_update_profile? YES -> update_profile")
        return "update_profile"

    # Otherwise, decide between response or search
    decision = "generate_response" if direct else "execute_queries"
    logger.info(
        "  [conditional] should_update_profile? NO -> decision",
        decision=decision,
    )
    return decision


def should_execute_queries(state: AssistantState) -> str:
    """Route after update_profile: either direct response or search."""
    direct = state.get("direct_response", False)
    decision = "generate_response" if direct else "execute_queries"
    logger.info(
        "  [conditional] should_execute_queries after profile update?",
        direct_response=direct,
        decision=decision,
    )
    return decision


def should_continue_after_acknowledgment(state: AssistantState) -> str:
    """Check force_response after acknowledgment before proceeding to plan_queries."""
    if state.get("force_response"):
        logger.info("  [conditional] force_response=True after acknowledgment, skipping to generate_response")
        return "generate_response"
    return "plan_queries"


def should_continue_after_execute(state: AssistantState) -> str:
    """Check force_response after execute_queries before proceeding to check_results."""
    if state.get("force_response"):
        logger.info("  [conditional] force_response=True after execute_queries, skipping to generate_response")
        return "generate_response"
    return "check_results"


def should_retry(state: AssistantState) -> str:
    """Route to relax_and_retry if there are zero-result tables and retries left.

    Also checks force_response — if a critical failure occurred, skip
    straight to generate_response.
    """
    if state.get("force_response"):
        logger.info("  [conditional] force_response=True, skipping retry to generate_response")
        return "generate_response"
    needs_retry = state.get("needs_retry", False)
    decision = "relax_and_retry" if needs_retry else "generate_response"
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

# fetch_data → generate_acknowledgment
graph_builder.add_edge("fetch_data", "generate_acknowledgment")

# generate_acknowledgment → conditional → plan_queries OR generate_response (force)
graph_builder.add_conditional_edges(
    "generate_acknowledgment",
    should_continue_after_acknowledgment,
    {
        "plan_queries": "plan_queries",
        "generate_response": "generate_response",
    },
)

# plan_queries → [Conditional: Update Profile or Execute/Response]
graph_builder.add_conditional_edges(
    "plan_queries",
    should_update_profile,
    {
        "update_profile": "update_profile",
        "execute_queries": "execute_queries",
        "generate_response": "generate_response",
    },
)

# update_profile → [Conditional: Execute or Response]
graph_builder.add_conditional_edges(
    "update_profile",
    should_execute_queries,
    {"execute_queries": "execute_queries", "generate_response": "generate_response"},
)

# execute_queries → conditional → check_results OR generate_response (force)
graph_builder.add_conditional_edges(
    "execute_queries",
    should_continue_after_execute,
    {
        "check_results": "check_results",
        "generate_response": "generate_response",
    },
)

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


# --- Progress messages, LLM tracking, SSE streaming logic (kept identical) ---

PROGRESS_MESSAGES = {
    "fetch_data": "Loading data...",
    "update_profile": "Updating your profile...",
    "generate_acknowledgment": None,
    "plan_queries": "Planning strategy...",
    "execute_queries": "Searching...",
    "check_results": "Analyzing results...",
    "relax_and_retry": "Expanding search...",
    "generate_response": "Preparing response...",
    "evaluate": None,
}


def _track_llm_usage(event: dict) -> dict | None:
    if event["event"] != "on_chat_model_end":
        return None
    output = event.get("data", {}).get("output")
    if not output:
        return None
    usage = getattr(output, "usage_metadata", None) or getattr(
        output, "response_metadata", {}
    ).get("usage")
    if not usage:
        return None
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
    if isinstance(usage, dict):
        input_tokens = usage.get("input_tokens", 0) or usage.get("prompt_tokens", 0)
        output_tokens = usage.get("output_tokens", 0) or usage.get(
            "completion_tokens", 0
        )
        cached_tokens = usage.get("cache_read_input_tokens", 0) or usage.get(
            "cache_creation_input_tokens", 0
        )
    else:
        input_tokens = getattr(usage, "input_tokens", 0)
        output_tokens = getattr(usage, "output_tokens", 0)
        cached_tokens = getattr(usage, "cache_read_input_tokens", 0)

    if input_tokens:
        LLM_TOKENS.labels(model=model, token_type="input").inc(input_tokens)
    if output_tokens:
        LLM_TOKENS.labels(model=model, token_type="output").inc(output_tokens)
    if cached_tokens:
        LLM_TOKENS.labels(model=model, token_type="cached").inc(cached_tokens)
    LLM_CALLS.labels(model=model, node=node).inc()
    return {
        "node": node,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "cached_tokens": cached_tokens,
    }


_PIPELINE_NODES = {
    "fetch_data",
    "update_profile",
    "generate_acknowledgment",
    "plan_queries",
    "execute_queries",
    "check_results",
    "relax_and_retry",
    "generate_response",
    "evaluate",
}
_LLM_NODES = {
    "plan_queries",
    "generate_response",
    "evaluate",
    "update_profile",
    "generate_acknowledgment",
}
_NODE_PROMPT_KEYS = {
    "plan_queries": "plan_queries",
    "generate_response": "generate_response",
    "evaluate": "evaluate",
    "update_profile": "profile_update",
    "generate_acknowledgment": "acknowledgment",
}


def _sanitize_for_debug(data: dict | None, max_str_len: int = 500) -> dict:
    if not data or not isinstance(data, dict):
        return {}
    result = {}
    skip_keys = {"messages", "progress_updates"}
    for key, value in data.items():
        if key in skip_keys:
            continue
        try:
            if isinstance(value, str) and len(value) > max_str_len:
                result[key] = value[:max_str_len] + "..."
            elif isinstance(value, list) and len(value) > 20:
                result[key] = value[:20]
                result[f"{key}_count"] = len(value)
            elif isinstance(value, dict) and len(str(value)) > 2000:
                result[key] = {k: "..." for k in list(value.keys())[:10]}
            else:
                json.dumps(value)
                result[key] = value
        except (TypeError, ValueError):
            result[key] = str(value)[:max_str_len]
    return result


async def stream_agent_response(
    message: str,
    user_context: dict,
    directus_writer: DirectusMessageWriter | None = None,
) -> AsyncGenerator[dict, None]:
    """Stream agent responses as SSE events with 30s timeout.

    Optionally writes response chunks to a Directus message record in parallel
    (for frontend WebSocket consumption). SSE events are always yielded regardless.

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
    full_response_text = ""
    logger.info(
        "========== PIPELINE START ==========",
        trace_id=trace_id,
        message=message[:200],
        user_context=user_context,
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
        "direct_response": False,
        "faq_id": None,
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
        # Graceful failure fields (Phase 2, TASK-01)
        "error_context": None,
        "partial_failure": False,
        "force_response": False,
    }

    seen_nodes: set[str] = set()
    done_sent = False
    ack_sent = False
    chunk_count = 0
    referenced_ids: list[str] = []
    debug = settings.debug_mode
    node_start_times: dict[str, float] = {}
    node_llm_usage: dict[str, dict] = {}
    node_last_output: dict[str, dict] = {}
    node_ended: set[str] = set()
    completed_nodes: list[dict] = []
    current_debug_node: str | None = None
    cache = get_cache_service()

    try:
        async for event in _stream_with_timeout(initial_state):
            kind = event["event"]
            metadata = event.get("metadata", {})
            langgraph_node = metadata.get("langgraph_node", "")
            llm_info = _track_llm_usage(event)
            if debug and llm_info and llm_info["node"] in _PIPELINE_NODES:
                node_llm_usage[llm_info["node"]] = llm_info

            if langgraph_node and langgraph_node not in seen_nodes:
                seen_nodes.add(langgraph_node)
                progress_msg = PROGRESS_MESSAGES.get(langgraph_node)
                elapsed = time.perf_counter() - request_start
                if debug and langgraph_node in _PIPELINE_NODES:
                    node_start_times[langgraph_node] = time.perf_counter()

                if not first_feedback_sent:
                    first_feedback_sent = True
                    TIME_TO_FIRST_FEEDBACK.observe(elapsed)

                yield {
                    "event": "progress",
                    "data": {"node": langgraph_node, "message": progress_msg},
                }

                # Directus streaming: write progress message
                if directus_writer and progress_msg:
                    await directus_writer.write_progress(progress_msg)

                # Debug: emit node_end for the PREVIOUS node (it just finished)
                if debug and current_debug_node and current_debug_node not in node_ended:
                    prev = current_debug_node
                    node_ended.add(prev)
                    now = time.perf_counter()
                    duration_ms = round((now - node_start_times.get(prev, now)) * 1000)
                    node_end_data = {
                        "node": prev,
                        "ts": time.time(),
                        "duration_ms": duration_ms,
                        "output": node_last_output.get(prev, {}),
                    }
                    if prev in node_llm_usage:
                        node_end_data["llm"] = node_llm_usage[prev]
                    completed_nodes.append(
                        {"node": prev, "duration_ms": duration_ms, "status": "ok"}
                    )
                    yield {"event": "node_end", "data": node_end_data}

                current_debug_node = langgraph_node
                if debug and langgraph_node in _PIPELINE_NODES:
                    node_start_data = {"node": langgraph_node, "ts": time.time()}
                    yield {"event": "node_start", "data": node_start_data}
                await cache.publish(
                    f"progress:{trace_id}",
                    json.dumps({"node": langgraph_node, "message": progress_msg}),
                )

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

                    # Directus streaming: write acknowledgment as initial message text
                    if directus_writer:
                        await directus_writer.write_acknowledgment(ack_text)
                else:
                    logger.info("  [sse] acknowledgment skipped (empty text)")

            if kind == "on_chain_end" and langgraph_node == "generate_response":
                output = event.get("data", {}).get("output", {})
                referenced_ids = (
                    output.get("referenced_ids", []) if isinstance(output, dict) else []
                )

            if kind == "on_chat_model_stream" and langgraph_node == "generate_response":
                chunk = event["data"].get("chunk")
                if chunk and chunk.content:
                    content = chunk.content
                    if isinstance(content, str):
                        chunk_count += 1
                        if not first_chunk_sent:
                            first_chunk_sent = True
                            TIME_TO_FIRST_CHUNK.observe(
                                time.perf_counter() - request_start
                            )
                        full_response_text += content
                        yield {"event": "chunk", "data": {"text": content}}
                        # Directus streaming: write chunk
                        if directus_writer:
                            await directus_writer.write_chunk(content)

            if (
                kind == "on_chain_end"
                and langgraph_node == "generate_response"
                and not done_sent
            ):
                # Check if we have a fallback response_text (error path) that wasn't streamed
                output = event.get("data", {}).get("output", {})
                if isinstance(output, dict):
                    fallback_text = output.get("response_text", "")
                    # If no chunks were streamed but we have response_text, send it now
                    if fallback_text and not full_response_text:
                        full_response_text = fallback_text
                        yield {"event": "chunk", "data": {"text": fallback_text}}
                        if directus_writer:
                            await directus_writer.write_chunk(fallback_text)
                
                done_sent = True
                if directus_writer:
                    await directus_writer.complete(
                        final_text=full_response_text,
                        metadata={
                            "trace_id": trace_id,
                            "referenced_ids": referenced_ids,
                        },
                    )
                yield {
                    "event": "done",
                    "data": {"trace_id": trace_id, "referenced_ids": referenced_ids},
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
        # Directus streaming: write error so message isn't left in streaming state
        if directus_writer:
            await directus_writer.error(
                error_info.get("error", "The request timed out. Please try again.")
            )
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
        # Directus streaming: write error so message isn't left in streaming state
        if directus_writer:
            await directus_writer.error(
                error_info.get("error", "Something went wrong. Please try again.")
            )
        yield {"event": "error", "data": error_info}

    if not done_sent:
        yield {
            "event": "done",
            "data": {"trace_id": trace_id, "referenced_ids": referenced_ids},
        }
    if debug and completed_nodes:
        total_tokens = {"input": 0, "output": 0, "cached": 0}
        for llm in node_llm_usage.values():
            for k in total_tokens:
                total_tokens[k] += llm.get(f"{k}_tokens", 0)
        yield {
            "event": "pipeline_summary",
            "data": {
                "trace_id": trace_id,
                "total_ms": round((time.perf_counter() - request_start) * 1000),
                "nodes": completed_nodes,
                "total_tokens": total_tokens,
            },
        }


async def _stream_with_timeout(initial_state: AssistantState):
    deadline = time.monotonic() + WORKFLOW_TIMEOUT
    async for event in graph.astream_events(initial_state, version="v2"):
        if time.monotonic() > deadline:
            raise asyncio.TimeoutError(f"Workflow exceeded {WORKFLOW_TIMEOUT}s timeout")
        yield event