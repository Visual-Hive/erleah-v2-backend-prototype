"""YAML-based facet configuration with weights."""

from functools import lru_cache
from pathlib import Path

import yaml
from pydantic import BaseModel


class FacetDefinition(BaseModel):
    key: str
    weight: float


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
