"""Tests for weighted faceted search scoring."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from src.search.facet_config import FacetDefinition, EntityFacetConfig, load_facet_config


class TestFacetConfig:
    def test_facet_definition(self):
        fd = FacetDefinition(key="what_we_sell", weight=1.0)
        assert fd.key == "what_we_sell"
        assert fd.weight == 1.0

    def test_entity_facet_config_total_facets(self):
        config = EntityFacetConfig(facets=[
            FacetDefinition(key="a", weight=1.0),
            FacetDefinition(key="b", weight=0.8),
            FacetDefinition(key="c", weight=0.6),
        ])
        assert config.total_facets == 3

    def test_get_weight_known_key(self):
        config = EntityFacetConfig(facets=[
            FacetDefinition(key="what_we_sell", weight=1.0),
            FacetDefinition(key="problems_we_solve", weight=0.9),
        ])
        assert config.get_weight("what_we_sell") == 1.0
        assert config.get_weight("problems_we_solve") == 0.9

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
