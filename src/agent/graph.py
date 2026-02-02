# src/agent/graph.py

from typing import AsyncGenerator

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from src.agent.state import AgentState
from src.config import settings

# Import Tools
from src.tools.exhibitor_search import ExhibitorSearchTool
from src.tools.session_search import SessionSearchTool

# Initialize Claude
llm = ChatAnthropic(
    model=settings.anthropic_model,
    api_key=settings.anthropic_api_key,
    temperature=0,
)

# Register Tools
TOOLS = [
    ExhibitorSearchTool(),
    SessionSearchTool(),
]

llm_with_tools = llm.bind_tools(TOOLS)

SYSTEM_PROMPT = """You are Erleah, an AI conference assistant. You help attendees find sessions, exhibitors, speakers, and navigate the conference. Use the available search tools to find relevant information before answering. Be concise and helpful."""


async def call_agent(state: AgentState) -> dict:
    """Node: Call the LLM with tools bound."""
    messages = state["messages"]
    iteration = state.get("iteration", 0)
    user_context = state.get("user_context", {})

    # Build system prompt with user context
    system_content = SYSTEM_PROMPT
    if user_context:
        system_content += f"\n\nUser context: {user_context}"
        if "conference_id" in user_context:
            system_content += f"\nAlways use conference_id=\"{user_context['conference_id']}\" when calling search tools."

    # Prepend system message if not present
    if not messages or not isinstance(messages[0], SystemMessage):
        messages = [SystemMessage(content=system_content)] + messages

    response = await llm_with_tools.ainvoke(messages)

    return {
        "messages": [response],
        "iteration": iteration + 1,
    }


async def execute_tools(state: AgentState) -> dict:
    """Node: Execute tools."""
    messages = state["messages"]
    last_message = messages[-1]

    tool_node = ToolNode(TOOLS)
    result = await tool_node.ainvoke({"messages": [last_message]})

    tool_messages = result["messages"]

    return {
        "messages": tool_messages,
    }


def should_continue(state: AgentState) -> str:
    """Edge: Decide whether to call tools or finish."""
    messages = state["messages"]
    last_message = messages[-1]
    iteration = state.get("iteration", 0)

    # Safety: stop after max iterations
    if iteration >= settings.max_iterations:
        return "end"

    # If the LLM made tool calls, execute them
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        return "tools"

    return "end"


# Build the graph
graph_builder = StateGraph(AgentState)
graph_builder.add_node("agent", call_agent)
graph_builder.add_node("tools", execute_tools)

graph_builder.set_entry_point("agent")
graph_builder.add_conditional_edges(
    "agent",
    should_continue,
    {"tools": "tools", "end": END},
)
graph_builder.add_edge("tools", "agent")

graph = graph_builder.compile()


async def stream_agent_response(
    message: str, user_context: dict
) -> AsyncGenerator[dict, None]:
    """Stream agent responses as events for SSE."""
    initial_state = {
        "messages": [HumanMessage(content=message)],
        "user_context": user_context,
        "plan": [],
        "tool_results": {},
        "needs_more_info": False,
        "iteration": 0,
    }

    async for event in graph.astream_events(initial_state, version="v2"):
        kind = event["event"]

        if kind == "on_chat_model_stream":
            chunk = event["data"].get("chunk")
            if chunk and chunk.content:
                content = chunk.content
                # Anthropic streams content as a list of blocks or a string
                if isinstance(content, list):
                    for block in content:
                        if isinstance(block, dict) and block.get("type") == "text":
                            text = block.get("text", "")
                            if text:
                                yield {
                                    "event": "message",
                                    "data": {"token": text},
                                }
                elif isinstance(content, str):
                    yield {
                        "event": "message",
                        "data": {"token": content},
                    }

        elif kind == "on_tool_start":
            yield {
                "event": "tool_execution",
                "data": {
                    "tool": event.get("name", ""),
                    "status": "started",
                },
            }

        elif kind == "on_tool_end":
            yield {
                "event": "tool_execution",
                "data": {
                    "tool": event.get("name", ""),
                    "status": "completed",
                },
            }

    yield {"event": "done", "data": {}}
