"""Helpers for consolidating Script 3 damage outputs.

Damage curves are emitted in pairs (C1/C2, C3/C4, C5/C6) for the same asset and
flood type. Summing every ``*_damage_value_mean`` column double-counts. These
helpers average the active pair per flood type, then sum across flood types.

Cost workbook values are in **million USD** per km-lane-unit (see Script 3).

Whole-asset rows: Script 3 splits each link into one row per raster-cell piece. Road
damage is priced per piece, so pieces are summed. Bridge and tunnel damage is priced
for the WHOLE structure (the structure length / replacement value, not the piece
length), so every piece of the same structure carries the same full-structure value.
Summing the pieces multiplied each structure's damage by its piece count (Harvey,
2026-11-12: $500B reported vs about $4.9B with each structure counted once). Totals
here therefore count a bridge or tunnel once per link (the maximum over its pieces)
and sum everything else.
"""

from __future__ import annotations

import re
from typing import Iterable

import numpy as np
import pandas as pd

from resiflow.parameters import get_parameter

CURVE_PAIRS: tuple[tuple[str, str], ...] = (
    ("C1", "C2"),
    ("C3", "C4"),
    ("C5", "C6"),
)
FLOOD_TYPES: tuple[str, ...] = ("surface", "river")
MUSD_TO_USD = get_parameter("damage_aggregation", "musd_to_usd", 1_000_000.0)

_MEAN_COL_RE = re.compile(
    r"^(C[1-6])_(surface|river)_damage_value_mean$", re.IGNORECASE
)


def mean_damage_columns(df: pd.DataFrame) -> list[str]:
    return [col for col in df.columns if col.endswith("_damage_value_mean")]


def consolidated_row_damage_musd(row: pd.Series) -> float:
    """Return consolidated direct damage for one intersection row (million USD)."""
    total = 0.0
    for flood_type in FLOOD_TYPES:
        pair_means: list[float] = []
        for curve_a, curve_b in CURVE_PAIRS:
            col_a = f"{curve_a}_{flood_type}_damage_value_mean"
            col_b = f"{curve_b}_{flood_type}_damage_value_mean"
            vals = [
                float(row[col])
                for col in (col_a, col_b)
                if col in row.index and pd.notna(row[col])
            ]
            if vals:
                pair_means.append(float(np.mean(vals)))
                break
        if pair_means:
            total += pair_means[0]
    return total


def add_consolidated_damage_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Add ``direct_damage_mean_musd`` and ``direct_damage_mean_usd`` columns.

    Costs already priced by Script 3 (the sourced path writes ``direct_damage_mean_musd`` and ``_usd``) are kept as they
    are. Recomputing from the legacy curve-pair columns would overwrite them with zeros (found 2026-11-12: it zeroed
    the sourced damage in ``3_postprocess_damage.py``).
    """
    out = df.copy()
    if "direct_damage_mean_musd" not in out.columns:
        out["direct_damage_mean_musd"] = out.apply(consolidated_row_damage_musd, axis=1)
    if "direct_damage_mean_usd" not in out.columns:
        out["direct_damage_mean_usd"] = pd.to_numeric(out["direct_damage_mean_musd"], errors="coerce") * MUSD_TO_USD
    return out


ASSET_LEVEL_LABELS: frozenset[str] = frozenset({"bridge", "tunnel"})


def asset_level_mask(df: pd.DataFrame) -> pd.Series:
    """True for rows whose damage value is for the whole structure (bridge, tunnel)."""
    if "road_label" not in df.columns:
        return pd.Series(False, index=df.index)
    return df["road_label"].astype(str).str.strip().str.lower().isin(ASSET_LEVEL_LABELS)


def collapse_to_edges(df: pd.DataFrame, value_cols: list[str]) -> pd.DataFrame:
    """One row per ``e_id``: sum road pieces, take bridge/tunnel whole-structure values once (max).

    ``value_cols`` must already exist in ``df``. Returns a frame indexed by ``e_id``.
    """
    if "e_id" not in df.columns:
        raise ValueError("damage dataframe must contain e_id")
    vals = df[value_cols].apply(pd.to_numeric, errors="coerce").fillna(0.0)
    vals["e_id"] = df["e_id"].to_numpy()
    asset = asset_level_mask(df).to_numpy()
    pieces = vals[~asset].groupby("e_id")[value_cols].sum()
    assets = vals[asset].groupby("e_id")[value_cols].max()
    return pd.concat([pieces, assets]).groupby(level=0).sum()


def _row_musd(df: pd.DataFrame) -> pd.Series:
    """Per-row consolidated damage in million USD, from whichever column is available."""
    if "direct_damage_mean_musd" in df.columns:
        return pd.to_numeric(df["direct_damage_mean_musd"], errors="coerce").fillna(0.0)
    if "direct_damage_mean_usd" in df.columns:
        return pd.to_numeric(df["direct_damage_mean_usd"], errors="coerce").fillna(0.0) / MUSD_TO_USD
    return df.apply(consolidated_row_damage_musd, axis=1)


def total_direct_damage_musd(df: pd.DataFrame) -> float:
    """Total direct damage (million USD), counting each bridge/tunnel once per link.

    Frames without ``e_id`` (toy fixtures) fall back to a plain row sum.
    """
    musd = _row_musd(df)
    if "e_id" not in df.columns:
        return float(musd.sum())
    frame = pd.DataFrame({"e_id": df["e_id"].to_numpy(), "musd": musd.to_numpy()}, index=df.index)
    if "road_label" in df.columns:
        frame["road_label"] = df["road_label"]
    return float(collapse_to_edges(frame, ["musd"])["musd"].sum())


def total_direct_damage_usd(df: pd.DataFrame) -> float:
    return total_direct_damage_musd(df) * MUSD_TO_USD


def consolidated_row_damage_bounds_musd(row: pd.Series) -> tuple[float, float]:
    """Return (low, high) direct damage bounds for one row (million USD).

    Mirrors ``consolidated_row_damage_musd``'s active-pair selection (first
    curve pair per flood type with a non-NaN mean), but pulls the underlying
    ``_damage_value_min``/``_damage_value_max`` cost-workbook bounds for that
    same pair instead of the mean, so the range reflects genuine unit-cost
    uncertainty already computed by Script 3 rather than a fabricated spread.
    """
    low_total = 0.0
    high_total = 0.0
    for flood_type in FLOOD_TYPES:
        for curve_a, curve_b in CURVE_PAIRS:
            mean_a = f"{curve_a}_{flood_type}_damage_value_mean"
            mean_b = f"{curve_b}_{flood_type}_damage_value_mean"
            active = [
                col
                for col in (mean_a, mean_b)
                if col in row.index and pd.notna(row[col])
            ]
            if not active:
                continue
            curves_present = [c for c, col in ((curve_a, mean_a), (curve_b, mean_b)) if col in active]
            lows = [
                float(row[f"{curve}_{flood_type}_damage_value_min"])
                for curve in curves_present
                if f"{curve}_{flood_type}_damage_value_min" in row.index
                and pd.notna(row[f"{curve}_{flood_type}_damage_value_min"])
            ]
            highs = [
                float(row[f"{curve}_{flood_type}_damage_value_max"])
                for curve in curves_present
                if f"{curve}_{flood_type}_damage_value_max" in row.index
                and pd.notna(row[f"{curve}_{flood_type}_damage_value_max"])
            ]
            if lows:
                low_total += float(np.mean(lows))
            if highs:
                high_total += float(np.mean(highs))
            break
    return low_total, high_total


def total_direct_damage_bounds_musd(df: pd.DataFrame) -> tuple[float, float]:
    if df.empty:
        return 0.0, 0.0
    bounds = df.apply(consolidated_row_damage_bounds_musd, axis=1, result_type="expand")
    if "e_id" not in df.columns:
        return float(bounds[0].sum()), float(bounds[1].sum())
    frame = pd.DataFrame({"e_id": df["e_id"].to_numpy(), "low": bounds[0].to_numpy(), "high": bounds[1].to_numpy()}, index=df.index)
    if "road_label" in df.columns:
        frame["road_label"] = df["road_label"]
    both = collapse_to_edges(frame, ["low", "high"])
    return float(both["low"].sum()), float(both["high"].sum())


def total_direct_damage_bounds_usd(df: pd.DataFrame) -> tuple[float, float]:
    low, high = total_direct_damage_bounds_musd(df)
    return low * MUSD_TO_USD, high * MUSD_TO_USD


def edge_level_damage_musd(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate consolidated segment damage to network edges."""
    if "e_id" not in df.columns:
        raise ValueError("damage dataframe must contain e_id")
    working = add_consolidated_damage_columns(df) if "direct_damage_mean_musd" not in df.columns else df
    return (
        collapse_to_edges(working, ["direct_damage_mean_musd"])
        .rename(columns={"direct_damage_mean_musd": "edge_direct_damage_mean_musd"})
        .reset_index()
    )


def legacy_sum_all_mean_columns_musd(df: pd.DataFrame) -> float:
    """Previous Script 4 behaviour (over-counts paired curves)."""
    cols = mean_damage_columns(df)
    if not cols:
        return 0.0
    return float(df[cols].apply(pd.to_numeric, errors="coerce").fillna(0).sum().sum())
