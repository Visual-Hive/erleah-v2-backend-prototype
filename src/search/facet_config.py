"""YAML-based facet configuration with weights and paired matching."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel


class FacetDefinition(BaseModel):
    key: str
    weight: float
    pair_with: str | None = None  # Complementary facet for buyer↔seller matching
    description: str = ""  # Human-readable description of what this facet represents


class EntityFacetConfig(BaseModel):
    facets: list[FacetDefinition]

    @property
    def total_facets(self) -> int:
        return len(self.facets)

    def get_weight(self, key: str) -> float:
        for f in self.facets:
            if f.key == key:
                return f.weight
        return 0.5  # Default weight for unknown facets

    def get_pair(self, key: str) -> str | None:
        """Get the paired facet key for buyer↔seller matching."""
        for f in self.facets:
            if f.key == key:
                return f.pair_with
        return None

    def get_facet_keys(self) -> list[str]:
        """Return all facet keys in order."""
        return [f.key for f in self.facets]

    def count_non_empty_facets(self, profile_facets: dict[str, str]) -> int:
        """Count facets that have non-empty values (>= 10 chars) in the profile."""
        count = 0
        for f in self.facets:
            value = profile_facets.get(f.key, "")
            if value and len(value) >= 10:
                count += 1
        return count


@lru_cache(maxsize=1)
def load_facet_config() -> dict[str, EntityFacetConfig]:
    """Load facet configuration from YAML. Cached after first call."""
    config_path = Path(__file__).parent.parent.parent / "config" / "facets.yaml"
    with open(config_path) as f:
        raw = yaml.safe_load(f)

    return {
        entity_type: EntityFacetConfig(facets=data["facets"])
        for entity_type, data in raw.items()
    }
