"""
Agent state definition for LangGraph.

AssistantState holds all information flowing through the 9-node pipeline.
"""

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AssistantState(TypedDict):
    """State schema for the conference assistant pipeline."""

    # Conversation history (automatically appended via reducer)
    messages: Annotated[list[BaseMessage], add_messages]

    # --- Request Metadata ---
    user_context: dict[str, Any]  # user_id, conference_id, etc.
    trace_id: str
    started_at: float  # Unix timestamp when request started
    completed_at: float | None  # Unix timestamp when request completed

    # --- fetch_data ---
    user_profile: dict[str, Any]
    conversation_history: list[dict]
    profile_needs_update: bool

    # --- update_profile ---
    profile_updates: dict[str, Any] | None
    profile_updated: bool  # Was profile updated this request?

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
    retry_metadata: dict[str, Any] | None  # Info about retries (removed_filters, etc.)

    # --- generate_response ---
    response_text: str
    referenced_ids: list[str]
    progress_updates: list[str]  # Progress messages shown to user

    # --- evaluate ---
    quality_score: float | None
    confidence_score: float | None
    evaluation: dict[str, Any] | None  # Structured evaluation {quality_score, confidence, suggestions}

    # --- generate_acknowledgment ---
    acknowledgment_text: str

    # --- control ---
    error: str | None
    error_node: str | None  # Which node failed
    current_node: str
