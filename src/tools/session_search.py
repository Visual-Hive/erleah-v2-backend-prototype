from typing import Any
from pydantic import BaseModel, Field
from src.tools.base import ErleahBaseTool
from src.search.faceted import hybrid_search


class SessionSearchInput(BaseModel):
    query: str = Field(description="Search query")
    conference_id: str = Field(description="Conference ID")
    use_faceted: bool = Field(
        default=True, description="Set False if searching exact title"
    )


class SessionSearchTool(ErleahBaseTool):
    name: str = "search_sessions"
    description: str = """
    Search for sessions, talks, or presentations.
    Use for: 'Find talks about marketing', 'What is happening at 2pm?', 'Keynote sessions'.
    """
    args_schema: type = SessionSearchInput

    async def _arun(
        self, query: str, conference_id: str, use_faceted: bool = True, **kwargs
    ) -> dict:
        try:
            results = await hybrid_search(
                entity_type="sessions",
                query=query,
                conference_id=conference_id,
                use_faceted=use_faceted,
            )

            formatted = []
            for r in results:
                formatted.append(
                    {
                        "title": r.payload.get("title"),
                        "time": r.payload.get("start_time"),
                        "location": r.payload.get("location"),
                        "speaker": r.payload.get("speaker_name"),
                        "description": r.payload.get("description"),
                    }
                )

            return {"results": formatted}
        except Exception as e:
            return self._handle_error(e)
