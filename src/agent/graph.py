"""
8-node LangGraph pipeline for the Erleah conference assistant.

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
from src.agent.state import AssistantState
from src.middleware.logging import trace_id_var

logger = structlog.get_logger()


# --- Conditional edges ---

def should_update_profile(state: AssistantState) -> str:
    """Route to update_profile if the message contains profile info."""
    if state.get("profile_needs_update", False):
        return "update_profile"
    return "generate_acknowledgment"


def should_retry(state: AssistantState) -> str:
    """Route to relax_and_retry if there are zero-result tables and retries left."""
    if state.get("needs_retry", False):
        return "relax_and_retry"
    return "generate_response"


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
    {"update_profile": "update_profile", "generate_acknowledgment": "generate_acknowledgment"},
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


async def stream_agent_response(
    message: str, user_context: dict
) -> AsyncGenerator[dict, None]:
    """Stream agent responses as SSE events.

    Event types:
    - acknowledgment: sent immediately (basic), then contextual from Grok node
    - progress: sent when each node starts (node name)
    - chunk: streamed response tokens (only from generate_response node)
    - done: sent after generate_response completes (before evaluate finishes)
    - error: sent on failures
    """
    initial_state: AssistantState = {
        "messages": [HumanMessage(content=message)],
        "user_context": user_context,
        "user_profile": {},
        "conversation_history": [],
        "profile_needs_update": False,
        "profile_updates": None,
        "intent": "",
        "query_mode": None,
        "planned_queries": [],
        "query_results": {},
        "zero_result_tables": [],
        "retry_count": 0,
        "needs_retry": False,
        "response_text": "",
        "referenced_ids": [],
        "quality_score": None,
        "confidence_score": None,
        "acknowledgment_text": "",
        "trace_id": trace_id_var.get(""),
        "error": None,
        "current_node": "",
    }

    # Send basic acknowledgment immediately
    yield {"event": "acknowledgment", "data": {"status": "processing"}}

    seen_nodes: set[str] = set()
    done_sent = False
    ack_sent = False

    async for event in graph.astream_events(initial_state, version="v2"):
        kind = event["event"]
        metadata = event.get("metadata", {})
        langgraph_node = metadata.get("langgraph_node", "")

        # Send progress events when a new node starts
        if langgraph_node and langgraph_node not in seen_nodes:
            seen_nodes.add(langgraph_node)
            yield {
                "event": "progress",
                "data": {"node": langgraph_node},
            }

        # Send contextual acknowledgment when generate_acknowledgment finishes
        if (
            kind == "on_chain_end"
            and langgraph_node == "generate_acknowledgment"
            and not ack_sent
        ):
            ack_sent = True
            # Extract ack text from the event output
            output = event.get("data", {}).get("output", {})
            ack_text = output.get("acknowledgment_text", "") if isinstance(output, dict) else ""
            if ack_text:
                yield {
                    "event": "acknowledgment",
                    "data": {"message": ack_text},
                }

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
                                yield {"event": "chunk", "data": {"token": text}}
                elif isinstance(content, str):
                    yield {"event": "chunk", "data": {"token": content}}

        # Detect when generate_response finishes → send done before evaluate
        if (
            kind == "on_chain_end"
            and langgraph_node == "generate_response"
            and not done_sent
        ):
            done_sent = True
            yield {"event": "done", "data": {}}

    # Fallback: if done was never sent (e.g. error path), send it now
    if not done_sent:
        yield {"event": "done", "data": {}}
