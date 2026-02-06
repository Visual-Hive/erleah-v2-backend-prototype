"""Tests for weighted faceted search scoring."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.search.facet_config import (
    FacetDefinition,
    EntityFacetConfig,
    load_facet_config,
)


class TestFacetConfig:
    def test_facet_definition(self):
        fd = FacetDefinition(
            key="selling_intent",
            weight=1.5,
            description="Products and services offered",
        )
        assert fd.key == "selling_intent"
        assert fd.weight == 1.5
        assert fd.description == "Products and services offered"

    def test_entity_facet_config_total_facets(self):
        config = EntityFacetConfig(
            facets=[
                FacetDefinition(key="a", weight=1.0),
                FacetDefinition(key="b", weight=0.8),
                FacetDefinition(key="c", weight=0.6),
            ]
        )
        assert config.total_facets == 3

    def test_get_weight_known_key(self):
        config = EntityFacetConfig(
            facets=[
                FacetDefinition(key="selling_intent", weight=1.5),
                FacetDefinition(key="seeking_to_meet", weight=1.2),
            ]
        )
        assert config.get_weight("selling_intent") == 1.5
        assert config.get_weight("seeking_to_meet") == 1.2

    def test_get_weight_unknown_key_returns_default(self):
        config = EntityFacetConfig(
            facets=[
                FacetDefinition(key="a", weight=1.0),
            ]
        )
        assert config.get_weight("unknown_facet") == 0.5

    def test_load_facet_config_returns_all_entity_types(self):
        # Clear lru_cache to ensure fresh load
        load_facet_config.cache_clear()
        config = load_facet_config()
        assert "exhibitors" in config
        assert "sessions" in config
        assert "speakers" in config

    def test_exhibitors_has_eight_facets(self):
        """Exhibitors now have 8 paired facets matching production vector_profile."""
        load_facet_config.cache_clear()
        config = load_facet_config()
        assert config["exhibitors"].total_facets == 8

    def test_sessions_has_six_facets(self):
        load_facet_config.cache_clear()
        config = load_facet_config()
        assert config["sessions"].total_facets == 6

    def test_speakers_has_five_facets(self):
        load_facet_config.cache_clear()
        config = load_facet_config()
        assert config["speakers"].total_facets == 5

    def test_attendees_has_eight_facets(self):
        load_facet_config.cache_clear()
        config = load_facet_config()
        assert "attendees" in config
        assert config["attendees"].total_facets == 8

    def test_attendee_paired_facets(self):
        """Attendee facets should have pair_with fields for buyer/seller matching."""
        load_facet_config.cache_clear()
        config = load_facet_config()
        attendees = config["attendees"]

        # Check specific pairs (production keys)
        sell_facet = next(f for f in attendees.facets if f.key == "selling_intent")
        buy_facet = next(f for f in attendees.facets if f.key == "buying_intent")
        assert sell_facet.pair_with == "buying_intent"
        assert buy_facet.pair_with == "selling_intent"

        i_am = next(f for f in attendees.facets if f.key == "i_am_this_person")
        seeking = next(f for f in attendees.facets if f.key == "seeking_to_meet")
        assert i_am.pair_with == "seeking_to_meet"
        assert seeking.pair_with == "i_am_this_person"

    def test_exhibitor_paired_facets(self):
        """Exhibitors now also have paired facets matching production schema."""
        load_facet_config.cache_clear()
        config = load_facet_config()
        exhibitors = config["exhibitors"]

        sell_facet = next(f for f in exhibitors.facets if f.key == "selling_intent")
        buy_facet = next(f for f in exhibitors.facets if f.key == "buying_intent")
        assert sell_facet.pair_with == "buying_intent"
        assert buy_facet.pair_with == "selling_intent"

    def test_get_pair_returns_paired_key(self):
        load_facet_config.cache_clear()
        config = load_facet_config()
        attendees = config["attendees"]
        assert attendees.get_pair("selling_intent") == "buying_intent"
        assert attendees.get_pair("i_am_this_person") == "seeking_to_meet"

    def test_get_pair_returns_none_for_unpaired(self):
        """Session facets have no pairs."""
        load_facet_config.cache_clear()
        config = load_facet_config()
        sessions = config["sessions"]
        assert sessions.get_pair("session_topic") is None

    def test_get_facet_keys(self):
        load_facet_config.cache_clear()
        config = load_facet_config()
        keys = config["exhibitors"].get_facet_keys()
        assert "selling_intent" in keys
        assert "buying_intent" in keys
        assert len(keys) == 8

    def test_count_non_empty_facets(self):
        """Adaptive breadth: only count facets with values >= 10 chars."""
        load_facet_config.cache_clear()
        config = load_facet_config()
        attendees = config["attendees"]
        profile = {
            "selling_intent": "Enterprise SaaS solutions for data analytics",
            "i_am_this_person": "CTO at a startup focusing on event tech",
            "services_seeking": "short",  # < 10 chars, should be skipped
            "challenges_facing": "",  # empty, should be skipped
        }
        count = attendees.count_non_empty_facets(profile)
        assert count == 2  # Only selling_intent and i_am_this_person qualify


class TestWeightedScoring:
    """Test the weighted scoring formula with known inputs."""

    def test_breadth_depth_composite_formula(self):
        """Verify: composite = (breadth * 0.4 + depth * 0.6) * 10"""
        # Example: 3 of 8 facets matched, depth=0.8
        breadth = 3 / 8  # 0.375
        depth = 0.8
        composite = (breadth * 0.4 + depth * 0.6) * 10
        assert abs(composite - 6.3) < 0.001

    def test_full_breadth_high_depth(self):
        """All facets matched with high similarity."""
        breadth = 8 / 8  # 1.0
        depth = 0.95
        composite = (breadth * 0.4 + depth * 0.6) * 10
        assert abs(composite - 9.7) < 0.001

    def test_single_facet_match(self):
        """Only one facet matched."""
        breadth = 1 / 8
        depth = 0.9
        composite = (breadth * 0.4 + depth * 0.6) * 10
        # (0.125 * 0.4 + 0.9 * 0.6) * 10 = (0.05 + 0.54) * 10 = 5.9
        assert 5.8 < composite < 6.0

    def test_weighted_depth_calculation(self):
        """Verify weighted average depth with different facet weights."""
        config = EntityFacetConfig(
            facets=[
                FacetDefinition(key="a", weight=1.0),
                FacetDefinition(key="b", weight=0.5),
            ]
        )

        facet_scores = {"a": 0.9, "b": 0.7}

        weighted_sum = 0.0
        weight_sum = 0.0
        for fk, score in facet_scores.items():
            w = config.get_weight(fk)
            weighted_sum += score * w
            weight_sum += w

        depth = weighted_sum / weight_sum
        # (0.9*1.0 + 0.7*0.5) / (1.0 + 0.5) = (0.9 + 0.35) / 1.5 = 0.8333
        assert abs(depth - 0.8333) < 0.001
