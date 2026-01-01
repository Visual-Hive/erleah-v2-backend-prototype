"""
Example tests for tools.

Run with: pytest tests/
"""

import pytest

from src.tools.vector_search import VectorSearchTool


@pytest.mark.asyncio
async def test_vector_search_tool_attendees():
    """Test vector search for attendees."""
    tool = VectorSearchTool()
    
    result = await tool._arun(
        query="Python developers",
        collection="attendees",
        limit=5,
    )
    
    assert result["success"] is True
    assert "data" in result
    assert "results" in result["data"]
    assert len(result["data"]["results"]) <= 5


@pytest.mark.asyncio
async def test_vector_search_tool_sessions():
    """Test vector search for sessions."""
    tool = VectorSearchTool()
    
    result = await tool._arun(
        query="machine learning",
        collection="sessions",
        limit=10,
    )
    
    assert result["success"] is True
    assert result["data"]["collection"] == "sessions"


@pytest.mark.asyncio
async def test_vector_search_tool_exhibitors():
    """Test vector search for exhibitors."""
    tool = VectorSearchTool()
    
    result = await tool._arun(
        query="data tools",
        collection="exhibitors",
        limit=5,
    )
    
    assert result["success"] is True
    assert result["data"]["count"] <= 5


# Add more tests as you build more tools
