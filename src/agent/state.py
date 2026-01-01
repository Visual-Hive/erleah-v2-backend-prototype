"""
Agent state definition for LangGraph.

The state holds all information the agent needs during a conversation turn.
"""

from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    """State schema for the conference assistant agent.
    
    This defines what information flows through the agent graph.
    """
    
    # Conversation history (automatically appended to)
    messages: Annotated[list[BaseMessage], add_messages]
    
    # User context (preferences, location, etc.)
    user_context: dict[str, any]
    
    # Agent's current plan (list of actions to take)
    plan: list[str]
    
    # Results from tool executions
    tool_results: dict[str, any]
    
    # Agent's reflection on whether it needs more info
    needs_more_info: bool
    
    # Iteration counter (to prevent infinite loops)
    iteration: int
