import structlog
from typing import Any, Optional
from pydantic import BaseModel, Field
from src.tools.base import ErleahBaseTool
from src.search.faceted import hybrid_search

logger = structlog.get_logger()


class ExhibitorSearchInput(BaseModel):
    query: str = Field(description="Search query")
    conference_id: str = Field(description="Conference ID")
    use_faceted: bool = Field(
        default=True,
        description="Set False only if searching for a specific company name",
    )


class ExhibitorSearchTool(ErleahBaseTool):
    name: str = "search_exhibitors"
    description: str = """
    Search for exhibitors, companies, or sponsors.
    Use for questions like: 'Who is selling AI tools?', 'Find booths about crypto', 'Is Google here?'
    """
    args_schema: type = ExhibitorSearchInput

    async def _arun(
        self, query: str, conference_id: str, use_faceted: bool = True, **kwargs
    ) -> dict:
        try:
            logger.info("exhibitor_search_start", query=query, conference_id=conference_id, use_faceted=use_faceted)
            results = await hybrid_search(
                entity_type="exhibitors",
                query=query,
                conference_id=conference_id,
                use_faceted=use_faceted,
            )
            logger.info("exhibitor_search_results", count=len(results))

            # Formatting for LLM
            formatted = []
            for r in results:
                formatted.append(
                    {
                        "name": r.payload.get("name"),
                        "description": r.payload.get("description"),
                        "booth": r.payload.get("booth_number"),
                        "relevance": f"{r.total_score:.2f}",
                    }
                )

            logger.info("exhibitor_search_formatted", formatted=formatted)
            return {"results": formatted}
        except Exception as e:
            logger.error("exhibitor_search_error", error=str(e), error_type=type(e).__name__)
            return self._handle_error(e)
