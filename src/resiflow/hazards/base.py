"""Hazard-agnostic protocols and shared datatypes."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

import geopandas as gpd
import pandas as pd


@dataclass(frozen=True)
class HazardEvent:
    """Resolved hazard scenario: metadata + source paths per intensity field."""

    hazard_type: str
    event_id: str
    intensity_unit: str
    sources: dict[str, list[str]] = field(default_factory=dict)
    clip_path: str | None = None
    flood_types: tuple[str, ...] = ("flood",)


@dataclass
class FragilityResult:
    """Outputs from operational and categorical fragility models."""

    max_speed: pd.Series | None = None
    damage_level_max: pd.Series | None = None
    damage_fractions: pd.DataFrame | None = None


class HazardSource(Protocol):
    """Loads hazard inputs; no routing or fragility."""

    hazard_type: str

    def resolve_event(self, event_id: str) -> HazardEvent: ...

    def list_events(self) -> list[str]: ...


class ExposureSampler(Protocol):
    """Raster/vector sampling to per-link intensity."""

    def sample_link_intensity(
        self,
        links: gpd.GeoDataFrame,
        hazard_event: HazardEvent,
        *,
        agg: str = "max",
    ) -> pd.DataFrame: ...


class OperationalFragility(Protocol):
  def apply(
      self,
      links: gpd.GeoDataFrame,
      intensity: pd.DataFrame,
      *,
      scenario_param: int,
  ) -> pd.Series: ...


class CategoricalFragility(Protocol):
    def apply(
        self,
        links: gpd.GeoDataFrame,
        intensity: pd.DataFrame,
        *,
        hazard_subtype: str = "flood",
    ) -> pd.Series: ...


def parse_hazard_config(entry: dict[str, Any]) -> dict[str, Any]:
    """Normalize a hazards.json event entry."""
    scenario_param = int(entry.get("scenario_param", entry.get("depth_key", 30)))
    closure = entry.get("closure_threshold")
    if closure is None:
        closure = entry.get("depth_key") or entry.get("snow_key_mm") or entry.get("ice_key_mm")
    return {
        "hazard_type": str(entry.get("hazard_type", "flood")),
        "event_id": str(entry.get("event_id", "1")),
        "scenario_param": scenario_param,
        "closure_threshold": int(closure) if closure is not None else scenario_param,
        "hazard_subtype": entry.get("hazard_subtype") or entry.get("flood_subtype"),
        "source": str(entry.get("source", "raster")),
    }


def resolve_hazard_source_path(config: dict[str, Any], base_path: Path) -> Path:
    """Default hazards.json location alongside study-area config."""
    explicit = config.get("hazards_config")
    if explicit:
        return Path(str(explicit))
    return base_path.parent / "hazards.json"
