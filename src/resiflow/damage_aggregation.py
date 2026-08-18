"""Helpers for consolidating Script 3 damage outputs.

Damage curves are emitted in pairs (C1/C2, C3/C4, C5/C6) for the same asset and
flood type. Summing every ``*_damage_value_mean`` column double-counts. These
helpers average the active pair per flood type, then sum across flood types.

Cost workbook values are in **million USD** per km-lane-unit (see Script 3).
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
    """Add ``direct_damage_mean_musd`` and ``direct_damage_mean_usd`` columns."""
    out = df.copy()
    out["direct_damage_mean_musd"] = out.apply(consolidated_row_damage_musd, axis=1)
    out["direct_damage_mean_usd"] = out["direct_damage_mean_musd"] * MUSD_TO_USD
    return out


def total_direct_damage_musd(df: pd.DataFrame) -> float:
    if "direct_damage_mean_musd" in df.columns:
        return float(pd.to_numeric(df["direct_damage_mean_musd"], errors="coerce").fillna(0).sum())
    return float(df.apply(consolidated_row_damage_musd, axis=1).sum())


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
    return float(bounds[0].sum()), float(bounds[1].sum())


def total_direct_damage_bounds_usd(df: pd.DataFrame) -> tuple[float, float]:
    low, high = total_direct_damage_bounds_musd(df)
    return low * MUSD_TO_USD, high * MUSD_TO_USD


def edge_level_damage_musd(df: pd.DataFrame) -> pd.DataFrame:
    """Aggregate consolidated segment damage to network edges."""
    if "e_id" not in df.columns:
        raise ValueError("damage dataframe must contain e_id")
    working = add_consolidated_damage_columns(df) if "direct_damage_mean_musd" not in df.columns else df
    return (
        working.groupby("e_id", as_index=False)["direct_damage_mean_musd"]
        .sum()
        .rename(columns={"direct_damage_mean_musd": "edge_direct_damage_mean_musd"})
    )


def legacy_sum_all_mean_columns_musd(df: pd.DataFrame) -> float:
    """Previous Script 4 behaviour (over-counts paired curves)."""
    cols = mean_damage_columns(df)
    if not cols:
        return 0.0
    return float(df[cols].apply(pd.to_numeric, errors="coerce").fillna(0).sum().sum())
