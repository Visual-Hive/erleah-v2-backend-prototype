"""
LangGraph agent definition.

This creates the agentic workflow: understand → plan → execute → reflect → respond.
"""

from langchain_anthropic import ChatAnthropic
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode

from src.agent.state import AgentState
from src.config import settings
from src.tools.vector_search import VectorSearchTool

# Initialize Claude
llm = ChatAnthropic(
    model=settings.anthropic_model,
    api_key=settings.anthropic_api_key,
    max_tokens=4096,
)

# Tool registry
TOOLS = [
    VectorSearchTool(),
    # Add more tools here as you build them
]

# Bind tools to LLM
llm_with_tools = llm.bind_tools(TOOLS)


def create_system_prompt(conference_data: dict | None = None) -> str:
    """Create system prompt with conference data for caching.
    
    Args:
        conference_data: Conference information to cache (attendees, sessions, etc.)
        
    Returns:
        System prompt string
    """
    base_prompt = """You are Erleah, an AI-powered conference assistant.

Your role is to help attendees:
- Find and connect with other attendees
- Discover relevant sessions and talks
- Navigate the conference venue
- Optimize their conference experience

You have access to tools for:
- Searching attendees, sessions, and exhibitors
- Analyzing conference maps and floor plans
- Calculating routes between locations
- Finding nearby points of interest

When using tools:
1. Think step-by-step about what information you need
2. Use tools to gather that information
3. Reflect on whether you have enough to answer
4. If not, use more tools
5. Once you have enough, provide a helpful response

Be proactive and suggest things the user might not have thought of.
Be concise but friendly. Stream your responses for better UX.
"""
    
    if conference_data:
        # This data will be cached with prompt caching
        data_section = f"""

Conference Data (cached):
{conference_data}
"""
        return base_prompt + data_section
    
    return base_prompt


async def understand_intent(state: AgentState) -> AgentState:
    """Node: Understand user's intent from their message.
    
    This is the first step - figure out what the user wants.
    """
    messages = state["messages"]
    user_context = state.get("user_context", {})
    
    # Get the latest user message
    user_message = messages[-1].content if messages else ""
    
    # For now, just pass through
    # In future, could add intent classification here
    
    return {
        **state,
        "iteration": state.get("iteration", 0) + 1,
    }


async def plan_actions(state: AgentState) -> AgentState:
    """Node: Create a plan of which tools to use.
    
    The agent decides what steps to take to answer the query.
    """
    messages = state["messages"]
    
    # Create system message with conference data
    # TODO: Load actual conference data from database
    conference_data = {}  # Placeholder
    system_prompt = create_system_prompt(conference_data)
    
    # Add system message
    full_messages = [SystemMessage(content=system_prompt)] + messages
    
    # Ask Claude to plan (without tool calling yet)
    planning_response = await llm.ainvoke(
        full_messages + [
            HumanMessage(content="""Before using tools, explain your plan:
1. What information do you need?
2. Which tools will you use?
3. In what order?

Keep it brief (2-3 sentences).""")
        ]
    )
    
    plan = planning_response.content
    
    return {
        **state,
        "plan": [plan],
    }


async def execute_tools(state: AgentState) -> AgentState:
    """Node: Execute tools based on Claude's decisions.
    
    Claude will decide which tools to call and with what arguments.
    """
    messages = state["messages"]
    
    # Create system message
    conference_data = {}  # TODO: Load from database
    system_prompt = create_system_prompt(conference_data)
    full_messages = [SystemMessage(content=system_prompt)] + messages
    
    # Let Claude decide which tools to use
    response = await llm_with_tools.ainvoke(full_messages)
    
    # Check if Claude wants to use tools
    if not response.tool_calls:
        # No tools needed, go straight to response
        return {
            **state,
            "messages": messages + [response],
            "needs_more_info": False,
        }
    
    # Execute tools using LangGraph's ToolNode
    tool_node = ToolNode(TOOLS)
    tool_results = await tool_node.ainvoke({"messages": messages + [response]})
    
    return {
        **state,
        "messages": messages + [response] + tool_results["messages"],
        "tool_results": {
            "executed": [call["name"] for call in response.tool_calls],
            "results": tool_results["messages"],
        },
    }


async def reflect(state: AgentState) -> AgentState:
    """Node: Reflect on whether we have enough information.
    
    The agent checks if it can answer or needs more tools.
    """
    messages = state["messages"]
    iteration = state.get("iteration", 0)
    
    # Safety: Don't loop forever
    if iteration >= settings.max_iterations:
        return {
            **state,
            "needs_more_info": False,
        }
    
    # Check if the last message has tool calls
    last_message = messages[-1] if messages else None
    
    if isinstance(last_message, AIMessage) and last_message.tool_calls:
        # Still executing tools, need more info
        return {
            **state,
            "needs_more_info": True,
        }
    
    # No tool calls, ready to respond
    return {
        **state,
        "needs_more_info": False,
    }


async def generate_response(state: AgentState) -> AgentState:
    """Node: Generate final response to user.
    
    Takes all the gathered information and creates a helpful response.
    """
    messages = state["messages"]
    
    # The messages already include tool results
    # Just get Claude's final response
    conference_data = {}  # TODO: Load from database
    system_prompt = create_system_prompt(conference_data)
    full_messages = [SystemMessage(content=system_prompt)] + messages
    
    response = await llm.ainvoke(full_messages)
    
    return {
        **state,
        "messages": messages + [response],
    }


def should_continue(state: AgentState) -> str:
    """Conditional edge: Decide whether to continue or finish.
    
    Returns:
        "continue" if agent needs more information
        "finish" if ready to respond
    """
    if state.get("needs_more_info", False):
        return "continue"
    return "finish"


# Build the graph
workflow = StateGraph(AgentState)

# Add nodes
workflow.add_node("understand", understand_intent)
workflow.add_node("plan", plan_actions)
workflow.add_node("execute", execute_tools)
workflow.add_node("reflect", reflect)
workflow.add_node("respond", generate_response)

# Add edges
workflow.set_entry_point("understand")
workflow.add_edge("understand", "plan")
workflow.add_edge("plan", "execute")
workflow.add_edge("execute", "reflect")

# Conditional edge: continue or finish
workflow.add_conditional_edges(
    "reflect",
    should_continue,
    {
        "continue": "execute",  # Loop back to execute more tools
        "finish": "respond",    # Move to final response
    },
)

workflow.add_edge("respond", END)

# Compile the graph
agent = workflow.compile()


async def stream_agent_response(
    message: str,
    user_context: dict | None = None,
) -> any:
    """Stream agent responses for real-time UI updates.
    
    Args:
        message: User's message
        user_context: Additional context (location, preferences, etc.)
        
    Yields:
        Dictionaries with event type and data for SSE streaming
    """
    # Initialize state
    initial_state: AgentState = {
        "messages": [HumanMessage(content=message)],
        "user_context": user_context or {},
        "plan": [],
        "tool_results": {},
        "needs_more_info": True,
        "iteration": 0,
    }
    
    # Stream agent execution
    async for output in agent.astream(initial_state):
        # Output is a dict with node name as key
        for node_name, node_output in output.items():
            if node_name == "plan":
                # Stream planning step
                plan = node_output.get("plan", [])
                if plan:
                    yield {
                        "event": "thinking",
                        "data": {
                            "step": "planning",
                            "plan": plan[0],
                        },
                    }
            
            elif node_name == "execute":
                # Stream tool execution
                tool_results = node_output.get("tool_results", {})
                if tool_results:
                    yield {
                        "event": "tool_execution",
                        "data": tool_results,
                    }
            
            elif node_name == "respond":
                # Stream final response
                messages = node_output.get("messages", [])
                if messages:
                    final_message = messages[-1]
                    if isinstance(final_message, AIMessage):
                        # Stream token by token
                        content = final_message.content
                        words = content.split()
                        
                        for word in words:
                            yield {
                                "event": "message",
                                "data": {"token": word + " "},
                            }
    
    # Done
    yield {
        "event": "done",
        "data": {"status": "complete"},
    }
