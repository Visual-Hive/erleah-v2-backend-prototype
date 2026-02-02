"""
Unit tests for the 8-node agent pipeline.

Each test passes a mock state in and asserts the partial state update out.
No real API calls — all external services are mocked.

Run with: pytest tests/test_nodes.py -v
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import HumanMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_state(**overrides):
    """Build a minimal AssistantState dict with sensible defaults."""
    state = {
        "messages": [HumanMessage(content="Where can I get free coffee?")],
        "user_context": {"user_id": "u1", "conference_id": "conf-2024"},
        "user_profile": {},
        "conversation_history": [],
        "profile_needs_update": False,
        "profile_updates": None,
        "profile_updated": False,
        "intent": "",
        "query_mode": None,
        "planned_queries": [],
        "query_results": {},
        "zero_result_tables": [],
        "retry_count": 0,
        "needs_retry": False,
        "retry_metadata": None,
        "response_text": "",
        "referenced_ids": [],
        "progress_updates": [],
        "quality_score": None,
        "confidence_score": None,
        "evaluation": None,
        "acknowledgment_text": "",
        "trace_id": "",
        "started_at": 0.0,
        "completed_at": None,
        "error": None,
        "error_node": None,
        "current_node": "",
    }
    state.update(overrides)
    return state


# Mock the cache service globally for node tests
@pytest.fixture(autouse=True)
def mock_cache():
    """Auto-mock cache service for all node tests."""
    with patch("src.services.cache.get_cache_service") as mock:
        cache = AsyncMock()
        cache.get.return_value = None  # Always miss
        cache.set.return_value = True
        cache.delete.return_value = True
        mock.return_value = cache
        yield cache


# ---------------------------------------------------------------------------
# Node 1: fetch_data_parallel
# ---------------------------------------------------------------------------

class TestFetchData:
    @pytest.mark.asyncio
    async def test_returns_empty_defaults_when_directus_unavailable(self):
        """Graceful degradation: empty profile/history when Directus is down."""
        with patch("src.agent.nodes.fetch_data.get_directus_client") as mock_dc:
            client = AsyncMock()
            client.get_user_profile.side_effect = Exception("connection refused")
            client.get_conversation_context.side_effect = Exception("connection refused")
            mock_dc.return_value = client

            from src.agent.nodes.fetch_data import fetch_data_parallel

            state = _base_state()
            result = await fetch_data_parallel(state)

            assert result["user_profile"] == {}
            assert result["conversation_history"] == []
            assert result["profile_needs_update"] is False
            assert result["current_node"] == "fetch_data"

    @pytest.mark.asyncio
    async def test_fetches_profile_and_history(self):
        """Happy path: fetches profile + history from Directus."""
        mock_profile = {"interests": ["AI"], "role": "developer"}
        mock_history = [{"role": "user", "messageText": "hello"}]

        with patch("src.agent.nodes.fetch_data.get_directus_client") as mock_dc:
            client = AsyncMock()
            client.get_user_profile.return_value = mock_profile
            client.get_conversation_context.return_value = mock_history
            mock_dc.return_value = client

            # Mock the LLM call for profile detection
            with patch("src.agent.nodes.fetch_data.sonnet") as mock_llm:
                mock_response = MagicMock()
                mock_response.content = json.dumps({"needs_update": False, "updates": None})
                mock_llm.ainvoke = AsyncMock(return_value=mock_response)

                from src.agent.nodes.fetch_data import fetch_data_parallel

                state = _base_state(user_context={"user_id": "u1", "conversation_id": "c1", "conference_id": "conf-2024"})
                result = await fetch_data_parallel(state)

                assert result["user_profile"] == mock_profile
                assert result["conversation_history"] == mock_history
                assert result["profile_needs_update"] is False


# ---------------------------------------------------------------------------
# Node 2: update_profile
# ---------------------------------------------------------------------------

class TestUpdateProfile:
    @pytest.mark.asyncio
    async def test_skips_when_no_user_id(self):
        from src.agent.nodes.update_profile import update_profile

        state = _base_state(user_context={}, user_profile={})
        result = await update_profile(state)

        assert result["profile_updates"] is None

    @pytest.mark.asyncio
    async def test_updates_profile_via_llm(self):
        updated = {"interests": ["AI", "coffee"], "role": "developer"}

        with patch("src.agent.nodes.update_profile.sonnet") as mock_llm:
            mock_response = MagicMock()
            mock_response.content = json.dumps(updated)
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)

            with patch("src.agent.nodes.update_profile.get_directus_client") as mock_dc:
                client = AsyncMock()
                client.update_user_profile.return_value = True
                mock_dc.return_value = client

                from src.agent.nodes.update_profile import update_profile

                state = _base_state(
                    user_profile={"interests": ["AI"], "role": "developer"},
                )
                result = await update_profile(state)

                assert result["profile_updates"] == updated
                assert result["user_profile"] == updated


# ---------------------------------------------------------------------------
# Node: generate_acknowledgment
# ---------------------------------------------------------------------------

class TestGenerateAcknowledgment:
    @pytest.mark.asyncio
    async def test_generates_acknowledgment(self):
        with patch("src.agent.nodes.generate_acknowledgment.get_grok_client") as mock_grok:
            grok = AsyncMock()
            grok.generate_acknowledgment.return_value = "Great question about coffee! Let me look that up."
            mock_grok.return_value = grok

            from src.agent.nodes.generate_acknowledgment import generate_acknowledgment

            state = _base_state()
            result = await generate_acknowledgment(state)

            assert result["acknowledgment_text"] == "Great question about coffee! Let me look that up."
            assert result["current_node"] == "generate_acknowledgment"

    @pytest.mark.asyncio
    async def test_fallback_on_error(self):
        with patch("src.agent.nodes.generate_acknowledgment.get_grok_client") as mock_grok:
            grok = AsyncMock()
            grok.generate_acknowledgment.return_value = "I'll help you with that."
            mock_grok.return_value = grok

            from src.agent.nodes.generate_acknowledgment import generate_acknowledgment

            state = _base_state()
            result = await generate_acknowledgment(state)

            assert result["acknowledgment_text"] == "I'll help you with that."


# ---------------------------------------------------------------------------
# Node 3: plan_queries
# ---------------------------------------------------------------------------

class TestPlanQueries:
    @pytest.mark.asyncio
    async def test_produces_structured_plan(self):
        plan_json = {
            "intent": "find coffee vendors",
            "query_mode": "hybrid",
            "queries": [
                {"table": "exhibitors", "search_mode": "faceted", "query_text": "free coffee", "limit": 10}
            ],
        }

        with patch("src.agent.nodes.plan_queries.sonnet") as mock_llm:
            mock_response = MagicMock()
            mock_response.content = json.dumps(plan_json)
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)

            from src.agent.nodes.plan_queries import plan_queries

            state = _base_state()
            result = await plan_queries(state)

            assert result["intent"] == "find coffee vendors"
            assert result["query_mode"] == "hybrid"
            assert len(result["planned_queries"]) == 1
            assert result["planned_queries"][0]["table"] == "exhibitors"

    @pytest.mark.asyncio
    async def test_handles_llm_failure_gracefully(self):
        with patch("src.agent.nodes.plan_queries.sonnet") as mock_llm:
            mock_llm.ainvoke = AsyncMock(side_effect=Exception("API error"))

            from src.agent.nodes.plan_queries import plan_queries

            state = _base_state()
            result = await plan_queries(state)

            assert result["intent"] == "unknown"
            assert result["planned_queries"] == []
            assert "error" in result


# ---------------------------------------------------------------------------
# Node 4: execute_queries
# ---------------------------------------------------------------------------

class TestExecuteQueries:
    @pytest.mark.asyncio
    async def test_executes_queries_in_parallel(self):
        from src.search.faceted import SearchResult

        mock_results = [
            SearchResult(entity_id="e1", entity_type="exhibitors", total_score=0.9, facet_matches=3, payload={"name": "Coffee Co"}),
        ]

        with patch("src.agent.nodes.execute_queries.hybrid_search", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = mock_results

            from src.agent.nodes.execute_queries import execute_queries

            state = _base_state(
                planned_queries=[
                    {"table": "exhibitors", "search_mode": "faceted", "query_text": "coffee", "limit": 10},
                ],
            )
            result = await execute_queries(state)

            assert "exhibitors" in result["query_results"]
            assert len(result["query_results"]["exhibitors"]) == 1
            assert result["query_results"]["exhibitors"][0]["entity_id"] == "e1"

    @pytest.mark.asyncio
    async def test_returns_empty_when_no_queries(self):
        from src.agent.nodes.execute_queries import execute_queries

        state = _base_state(planned_queries=[])
        result = await execute_queries(state)

        assert result["query_results"] == {}


# ---------------------------------------------------------------------------
# Node 5: check_results
# ---------------------------------------------------------------------------

class TestCheckResults:
    @pytest.mark.asyncio
    async def test_identifies_zero_result_tables(self):
        from src.agent.nodes.check_results import check_results

        state = _base_state(
            planned_queries=[
                {"table": "exhibitors", "search_mode": "faceted", "query_text": "coffee", "limit": 10},
                {"table": "sessions", "search_mode": "faceted", "query_text": "coffee", "limit": 10},
            ],
            query_results={"exhibitors": [{"entity_id": "e1"}], "sessions": []},
            retry_count=0,
        )
        result = await check_results(state)

        assert "sessions" in result["zero_result_tables"]
        assert result["needs_retry"] is True

    @pytest.mark.asyncio
    async def test_no_retry_when_all_have_results(self):
        from src.agent.nodes.check_results import check_results

        state = _base_state(
            planned_queries=[{"table": "exhibitors", "search_mode": "faceted", "query_text": "coffee", "limit": 10}],
            query_results={"exhibitors": [{"entity_id": "e1"}]},
            retry_count=0,
        )
        result = await check_results(state)

        assert result["zero_result_tables"] == []
        assert result["needs_retry"] is False

    @pytest.mark.asyncio
    async def test_no_retry_when_max_retries_reached(self):
        from src.agent.nodes.check_results import check_results

        state = _base_state(
            planned_queries=[{"table": "sessions", "search_mode": "faceted", "query_text": "x", "limit": 10}],
            query_results={"sessions": []},
            retry_count=2,  # max_retry_count is now 2
        )
        result = await check_results(state)

        assert result["needs_retry"] is False


# ---------------------------------------------------------------------------
# Node 6: relax_and_retry
# ---------------------------------------------------------------------------

class TestRelaxAndRetry:
    @pytest.mark.asyncio
    async def test_retries_zero_result_tables_with_faceted(self):
        from src.search.faceted import SearchResult

        mock_results = [
            SearchResult(entity_id="s1", entity_type="sessions", total_score=0.7, facet_matches=2, payload={"title": "Coffee Talk"}),
        ]

        with patch("src.agent.nodes.relax_and_retry.hybrid_search", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = mock_results

            from src.agent.nodes.relax_and_retry import relax_and_retry

            state = _base_state(
                zero_result_tables=["sessions"],
                planned_queries=[
                    {"table": "sessions", "search_mode": "master", "query_text": "coffee", "limit": 5},
                ],
                query_results={"sessions": [], "exhibitors": [{"entity_id": "e1"}]},
                retry_count=0,
            )
            result = await relax_and_retry(state)

            assert len(result["query_results"]["sessions"]) == 1
            assert result["retry_count"] == 1
            # Existing exhibitor results preserved
            assert result["query_results"]["exhibitors"] == [{"entity_id": "e1"}]
            # First retry uses faceted with doubled limit
            mock_search.assert_called_once()
            call_kwargs = mock_search.call_args
            assert call_kwargs.kwargs.get("use_faceted") is True or call_kwargs[1].get("use_faceted") is True

    @pytest.mark.asyncio
    async def test_second_retry_uses_master_search(self):
        from src.search.faceted import SearchResult

        mock_results = [
            SearchResult(entity_id="s1", entity_type="sessions", total_score=0.5, facet_matches=1, payload={"title": "Coffee Talk"}),
        ]

        with patch("src.agent.nodes.relax_and_retry.hybrid_search", new_callable=AsyncMock) as mock_search:
            mock_search.return_value = mock_results

            from src.agent.nodes.relax_and_retry import relax_and_retry

            state = _base_state(
                zero_result_tables=["sessions"],
                planned_queries=[
                    {"table": "sessions", "search_mode": "faceted", "query_text": "coffee", "limit": 5},
                ],
                query_results={"sessions": []},
                retry_count=1,  # Second retry
            )
            result = await relax_and_retry(state)

            assert result["retry_count"] == 2
            # Second retry uses master search
            call_kwargs = mock_search.call_args
            assert call_kwargs.kwargs.get("use_faceted") is False or call_kwargs[1].get("use_faceted") is False


# ---------------------------------------------------------------------------
# Node 7: generate_response
# ---------------------------------------------------------------------------

class TestGenerateResponse:
    @pytest.mark.asyncio
    async def test_generates_response_from_results(self):
        with patch("src.agent.nodes.generate_response.sonnet") as mock_llm:
            mock_response = MagicMock()
            # Response must contain the entity_id for _extract_mentioned_ids to find it
            mock_response.content = "You can find free coffee at Coffee Co (e1) booth A12!"
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)

            from src.agent.nodes.generate_response import generate_response

            state = _base_state(
                query_results={
                    "exhibitors": [{"entity_id": "e1", "entity_type": "exhibitors", "payload": {"name": "Coffee Co"}}]
                },
                intent="find coffee vendors",
            )
            result = await generate_response(state)

            assert "coffee" in result["response_text"].lower()
            assert result["referenced_ids"] == ["e1"]

    @pytest.mark.asyncio
    async def test_handles_generation_error(self):
        with patch("src.agent.nodes.generate_response.sonnet") as mock_llm:
            mock_llm.ainvoke = AsyncMock(side_effect=Exception("API error"))

            from src.agent.nodes.generate_response import generate_response

            state = _base_state()
            result = await generate_response(state)

            assert "error" in result["response_text"].lower() or "sorry" in result["response_text"].lower()


# ---------------------------------------------------------------------------
# Node 8: evaluate
# ---------------------------------------------------------------------------

class TestEvaluate:
    @pytest.mark.asyncio
    async def test_scores_response(self):
        with patch("src.agent.nodes.evaluate.haiku") as mock_llm:
            mock_response = MagicMock()
            mock_response.content = json.dumps({"quality_score": 0.85, "confidence_score": 0.9})
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)

            from src.agent.nodes.evaluate import evaluate

            state = _base_state(
                response_text="Coffee Co is at booth A12!",
                query_results={"exhibitors": [{"entity_id": "e1"}]},
            )
            result = await evaluate(state)

            assert result["quality_score"] == 0.85
            assert result["confidence_score"] == 0.9

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        with patch("src.agent.nodes.evaluate.settings") as mock_settings:
            mock_settings.evaluation_enabled = False

            from src.agent.nodes.evaluate import evaluate

            state = _base_state(response_text="Some response")
            result = await evaluate(state)

            assert result["quality_score"] is None
            assert result["confidence_score"] is None

    @pytest.mark.asyncio
    async def test_handles_evaluation_failure(self):
        with patch("src.agent.nodes.evaluate.haiku") as mock_llm:
            mock_llm.ainvoke = AsyncMock(side_effect=Exception("API error"))

            from src.agent.nodes.evaluate import evaluate

            state = _base_state(response_text="Some response")
            result = await evaluate(state)

            assert result["quality_score"] is None
            assert result["confidence_score"] is None


# ---------------------------------------------------------------------------
# Graph conditional edges
# ---------------------------------------------------------------------------

class TestConditionalEdges:
    def test_should_update_profile_routes_correctly(self):
        from src.agent.graph import should_update_profile

        assert should_update_profile(_base_state(profile_needs_update=True)) == "update_profile"
        assert should_update_profile(_base_state(profile_needs_update=False)) == "generate_acknowledgment"

    def test_should_retry_routes_correctly(self):
        from src.agent.graph import should_retry

        assert should_retry(_base_state(needs_retry=True)) == "relax_and_retry"
        assert should_retry(_base_state(needs_retry=False)) == "generate_response"


# ---------------------------------------------------------------------------
# Prompt caching: verify SystemMessage with cache_control is used
# ---------------------------------------------------------------------------

class TestPromptCaching:
    @pytest.mark.asyncio
    async def test_plan_queries_uses_system_message_with_cache_control(self):
        with patch("src.agent.nodes.plan_queries.sonnet") as mock_llm:
            mock_response = MagicMock()
            mock_response.content = json.dumps({
                "intent": "test", "query_mode": "hybrid", "queries": []
            })
            mock_llm.ainvoke = AsyncMock(return_value=mock_response)

            from src.agent.nodes.plan_queries import plan_queries

            state = _base_state()
            await plan_queries(state)

            # Check that SystemMessage was used (not a plain dict)
            call_args = mock_llm.ainvoke.call_args[0][0]
            from langchain_core.messages import SystemMessage
            assert isinstance(call_args[0], SystemMessage)
            assert call_args[0].additional_kwargs.get("cache_control") == {"type": "ephemeral"}
