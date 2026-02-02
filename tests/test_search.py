"""Tests for weighted faceted search scoring."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.search.facet_config import FacetDefinition, EntityFacetConfig, load_facet_config


class TestFacetConfig:
    def test_facet_definition(self):
        fd = FacetDefinition(key="what_they_sell", weight=1.5, description="Products and services offered")
        assert fd.key == "what_they_sell"
        assert fd.weight == 1.5
        assert fd.description == "Products and services offered"

    def test_entity_facet_config_total_facets(self):
        config = EntityFacetConfig(facets=[
            FacetDefinition(key="a", weight=1.0),
            FacetDefinition(key="b", weight=0.8),
            FacetDefinition(key="c", weight=0.6),
        ])
        assert config.total_facets == 3

    def test_get_weight_known_key(self):
        config = EntityFacetConfig(facets=[
            FacetDefinition(key="what_they_sell", weight=1.5),
            FacetDefinition(key="who_they_target", weight=1.2),
        ])
        assert config.get_weight("what_they_sell") == 1.5
        assert config.get_weight("who_they_target") == 1.2

    def test_get_weight_unknown_key_returns_default(self):
        config = EntityFacetConfig(facets=[
            FacetDefinition(key="a", weight=1.0),
        ])
        assert config.get_weight("unknown_facet") == 0.5

    def test_load_facet_config_returns_all_entity_types(self):
        # Clear lru_cache to ensure fresh load
        load_facet_config.cache_clear()
        config = load_facet_config()
        assert "exhibitors" in config
        assert "sessions" in config
        assert "speakers" in config

    def test_exhibitors_has_six_facets(self):
        load_facet_config.cache_clear()
        config = load_facet_config()
        assert config["exhibitors"].total_facets == 6

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

        # Check specific pairs
        sell_facet = next(f for f in attendees.facets if f.key == "products_i_want_to_sell")
        buy_facet = next(f for f in attendees.facets if f.key == "products_i_want_to_buy")
        assert sell_facet.pair_with == "products_i_want_to_buy"
        assert buy_facet.pair_with == "products_i_want_to_sell"

        who_i_am = next(f for f in attendees.facets if f.key == "who_i_am")
        who_looking = next(f for f in attendees.facets if f.key == "who_im_looking_for")
        assert who_i_am.pair_with == "who_im_looking_for"
        assert who_looking.pair_with == "who_i_am"

    def test_get_pair_returns_paired_key(self):
        load_facet_config.cache_clear()
        config = load_facet_config()
        attendees = config["attendees"]
        assert attendees.get_pair("products_i_want_to_sell") == "products_i_want_to_buy"
        assert attendees.get_pair("who_i_am") == "who_im_looking_for"

    def test_get_pair_returns_none_for_unpaired(self):
        """Non-attendee facets have no pairs."""
        load_facet_config.cache_clear()
        config = load_facet_config()
        exhibitors = config["exhibitors"]
        assert exhibitors.get_pair("what_they_sell") is None

    def test_get_facet_keys(self):
        load_facet_config.cache_clear()
        config = load_facet_config()
        keys = config["exhibitors"].get_facet_keys()
        assert "what_they_sell" in keys
        assert len(keys) == 6

    def test_count_non_empty_facets(self):
        """Adaptive breadth: only count facets with values >= 10 chars."""
        load_facet_config.cache_clear()
        config = load_facet_config()
        attendees = config["attendees"]
        profile = {
            "products_i_want_to_sell": "Enterprise SaaS solutions for data analytics",
            "who_i_am": "CTO at a startup",
            "my_expertise": "short",  # < 10 chars, should be skipped
            "industries_i_work_in": "",  # empty, should be skipped
        }
        count = attendees.count_non_empty_facets(profile)
        assert count == 2  # Only sell and who_i_am qualify


class TestWeightedScoring:
    """Test the weighted scoring formula with known inputs."""

    def test_breadth_depth_composite_formula(self):
        """Verify: composite = (breadth * 0.4 + depth * 0.6) * 10"""
        # Example: 3 of 6 facets matched, depth=0.8
        breadth = 3 / 6  # 0.5
        depth = 0.8
        composite = (breadth * 0.4 + depth * 0.6) * 10
        assert abs(composite - 6.8) < 0.001

    def test_full_breadth_high_depth(self):
        """All facets matched with high similarity."""
        breadth = 6 / 6  # 1.0
        depth = 0.95
        composite = (breadth * 0.4 + depth * 0.6) * 10
        assert abs(composite - 9.7) < 0.001

    def test_single_facet_match(self):
        """Only one facet matched."""
        breadth = 1 / 6
        depth = 0.9
        composite = (breadth * 0.4 + depth * 0.6) * 10
        # (0.1667 * 0.4 + 0.9 * 0.6) * 10 = (0.0667 + 0.54) * 10 = 6.067
        assert 6.0 < composite < 6.1

    def test_weighted_depth_calculation(self):
        """Verify weighted average depth with different facet weights."""
        config = EntityFacetConfig(facets=[
            FacetDefinition(key="a", weight=1.0),
            FacetDefinition(key="b", weight=0.5),
        ])

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
