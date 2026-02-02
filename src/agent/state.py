"""
Agent state definition for LangGraph.

AssistantState holds all information flowing through the 8-node pipeline.
"""

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AssistantState(TypedDict):
    """State schema for the 8-node conference assistant pipeline."""

    # Conversation history (automatically appended via reducer)
    messages: Annotated[list[BaseMessage], add_messages]

    # User context passed from the request
    user_context: dict[str, Any]  # user_id, conference_id, etc.

    # --- fetch_data ---
    user_profile: dict[str, Any]
    conversation_history: list[dict]
    profile_needs_update: bool

    # --- update_profile ---
    profile_updates: dict[str, Any] | None

    # --- plan_queries ---
    intent: str
    query_mode: Literal["specific", "profile", "hybrid"] | None
    planned_queries: list[dict]  # [{table, search_mode, query_text, filters, limit}]

    # --- execute_queries ---
    query_results: dict[str, list]  # {table_name: [SearchResult, ...]}

    # --- check_results ---
    zero_result_tables: list[str]
    retry_count: int
    needs_retry: bool

    # --- generate_response ---
    response_text: str
    referenced_ids: list[str]

    # --- evaluate ---
    quality_score: float | None
    confidence_score: float | None

    # --- generate_acknowledgment ---
    acknowledgment_text: str

    # --- control ---
    trace_id: str
    error: str | None
    current_node: str
