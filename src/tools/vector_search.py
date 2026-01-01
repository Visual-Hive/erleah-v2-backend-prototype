"""
Vector search tool for semantic search across conference data.

Searches attendees, sessions, and exhibitors using vector embeddings.
"""

from typing import Literal

from pydantic import Field

from src.tools.base import ErleahBaseTool


class VectorSearchTool(ErleahBaseTool):
    """Search conference data using semantic/vector search.
    
    This tool uses embeddings to find relevant attendees, sessions, or
    exhibitors based on natural language queries.
    
    Examples:
        - "Find Python developers"
        - "Sessions about AI and machine learning"
        - "Exhibitors in the healthcare space"
    """
    
    name: str = "vector_search"
    description: str = """
    Search for attendees, sessions, or exhibitors using semantic search.
    
    Use this when the user asks about:
    - Finding people with specific skills or interests
    - Discovering relevant sessions or talks
    - Locating exhibitors in a particular domain
    
    The search uses AI embeddings to find semantically similar results,
    so it works even if the exact keywords don't match.
    
    Input:
        query: What to search for (natural language)
        collection: Which data to search (attendees/sessions/exhibitors)
        limit: Maximum number of results (default 10)
    
    Returns:
        List of relevant results with similarity scores
    """
    
    query: str = Field(description="Natural language search query")
    collection: Literal["attendees", "sessions", "exhibitors"] = Field(
        description="Which collection to search"
    )
    limit: int = Field(default=10, description="Maximum results to return")
    
    async def _arun(
        self,
        query: str,
        collection: str,
        limit: int = 10,
    ) -> dict:
        """Execute vector search.
        
        Args:
            query: Search query
            collection: Collection to search
            limit: Max results
            
        Returns:
            Search results with scores
        """
        # TODO: Implement actual vector search with Qdrant
        # For now, return mock data
        
        mock_results = {
            "attendees": [
                {
                    "id": "att-001",
                    "name": "Sarah Chen",
                    "title": "Senior Python Developer",
                    "company": "TechCorp",
                    "interests": ["Python", "Machine Learning", "Open Source"],
                    "score": 0.92,
                },
                {
                    "id": "att-002",
                    "name": "Michael Rodriguez",
                    "title": "Data Scientist",
                    "company": "DataCo",
                    "interests": ["Python", "Statistics", "Deep Learning"],
                    "score": 0.87,
                },
            ],
            "sessions": [
                {
                    "id": "ses-101",
                    "title": "Advanced Python for Data Science",
                    "speaker": "Dr. Jane Smith",
                    "time": "2024-03-15T14:00:00Z",
                    "location": "Hall A",
                    "score": 0.95,
                },
            ],
            "exhibitors": [
                {
                    "id": "exh-201",
                    "name": "PyData Solutions",
                    "booth": "E-47",
                    "category": "Data Tools",
                    "score": 0.89,
                },
            ],
        }
        
        # Get mock results for requested collection
        results = mock_results.get(collection, [])
        
        # Limit results
        results = results[:limit]
        
        return {
            "success": True,
            "data": {
                "query": query,
                "collection": collection,
                "results": results,
                "count": len(results),
            },
            "error": None,
        }
