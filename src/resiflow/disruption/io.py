"""I/O helpers for disruption pipeline outputs."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import geopandas as gpd


def first_existing(paths):
    """Return first existing path from a sequence, else None."""
    for path in paths:
        p = Path(path)
        if p.exists():
            return p
    return None


def validate_output(path: Path, gdf: gpd.GeoDataFrame, label: str) -> None:
    """Basic validation for outputs (non-empty + file exists)."""
    if gdf is None or gdf.empty:
        logging.warning(f"{label} is empty. Output not written: {path}")
        return
    if path.exists():
        size = os.path.getsize(path)
        if size == 0:
            logging.warning(f"{label} file is empty: {path}")
        else:
            logging.info(f"{label} saved: {path} (rows={len(gdf)}, bytes={size})")
    else:
        logging.warning(f"{label} file missing after save: {path}")


def log_summary(label: str, gdf: gpd.GeoDataFrame) -> None:
    """Log quick summary stats for outputs."""
    if gdf is None or gdf.empty:
        return

    if "flood_depth_max" in gdf.columns:
        depth = gdf["flood_depth_max"].astype(float)
        logging.info(
            f"{label} flood_depth_max: min={depth.min():.4f}, max={depth.max():.4f}, mean={depth.mean():.4f}"
        )

    if "damage_level_max" in gdf.columns:
        counts = gdf["damage_level_max"].value_counts(dropna=False)
        logging.info(f"{label} damage_level_max counts: {counts.to_dict()}")
