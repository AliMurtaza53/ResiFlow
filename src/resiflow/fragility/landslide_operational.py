"""Landslide operational fragility: damage state → max_speed (T36 roadway/bridge fork)."""

from __future__ import annotations

import pandas as pd

from resiflow.fragility.earthquake_operational import (
    apply_max_speed_to_links as _apply_max_speed_to_links,
)


def apply_max_speed_to_links(
    road_links: pd.DataFrame,
    **kwargs,
) -> pd.DataFrame:
    kwargs.setdefault("hazard", "landslide")
    return _apply_max_speed_to_links(road_links, **kwargs)


__all__ = ["apply_max_speed_to_links"]
