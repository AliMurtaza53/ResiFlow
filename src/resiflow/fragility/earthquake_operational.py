"""Earthquake / landslide operational fragility: damage state → max_speed.

Replaces the prior hardcoded PLACEHOLDER dict (1.0/0.85/0.5/0/0) with
HAZUS EQ Technical Manual 6.1 Table 7-4 day-1 Functional Percentage values
from ``T36_damage_state_operational_factors`` (forked by hazard × bridge|road).

HAZUS reports undifferentiated functionality (not separate speed vs capacity);
table ``speed_factor`` equals ``capacity_factor``. ``p_closed=1`` → max_speed=0.
Day-1 factors only — T26 owns multi-day capacity recovery (do not also apply
HAZUS day-N restoration in the same run).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from resiflow.parameters import get_parameter
from resiflow.tables import load_table

_REQUIRED_STATES = ("no", "minor", "moderate", "extensive", "severe")


def _factor_map(table: pd.DataFrame, hazard: str) -> dict[tuple[str, str], float]:
    """(asset, damage_state) → speed_factor for one hazard; raise if any cell missing."""
    out: dict[tuple[str, str], float] = {}
    for asset in ("bridge", "road"):
        for ds in _REQUIRED_STATES:
            rows = table.loc[
                (table["hazard"].astype(str).str.lower() == hazard.lower())
                & (table["asset"].astype(str).str.lower() == asset)
                & (table["damage_state"].astype(str).str.lower() == ds)
            ]
            if rows.empty:
                raise KeyError(
                    f"T36 missing row for hazard={hazard!r} asset={asset!r} "
                    f"damage_state={ds!r}"
                )
            row = rows.iloc[0]
            if float(row["p_closed"]) >= 1.0:
                out[(asset, ds)] = 0.0
                continue
            if pd.isna(row["speed_factor"]):
                raise KeyError(
                    f"T36 row hazard={hazard!r} asset={asset!r} damage_state={ds!r} "
                    "missing required speed_factor"
                )
            out[(asset, ds)] = float(row["speed_factor"])
    return out


def apply_max_speed_to_links(
    road_links: pd.DataFrame,
    *,
    hazard: str = "earthquake",
    damage_col: str = "damage_level_max",
    free_flow_col: str = "free_flow_speeds",
    out_col: str = "max_speed",
    bridge_col: str = "road_bridge",
) -> pd.DataFrame:
    """Apply T36 day-1 speed factors: max_speed = free_flow × factor(hazard, asset, DS)."""
    table_name = get_parameter(
        "hazard_disruption",
        "damage_state_operational_table",
        "T36_damage_state_operational_factors",
    )
    table = load_table(table_name)
    for col in ("hazard", "asset", "damage_state", "speed_factor", "p_closed"):
        if col not in table.columns:
            raise KeyError(
                f"{table_name} missing required column {col!r}; found {list(table.columns)}"
            )
    fmap = _factor_map(table, hazard)

    out = road_links.copy()
    if free_flow_col not in out.columns:
        raise KeyError(f"road_links missing required free-flow column {free_flow_col!r}")
    if damage_col not in out.columns:
        raise KeyError(f"road_links missing required damage column {damage_col!r}")

    free_flow = pd.to_numeric(out[free_flow_col], errors="coerce")
    if free_flow.isna().any():
        raise ValueError(
            f"{free_flow_col} has {int(free_flow.isna().sum())} non-numeric/missing "
            "values; refuse to invent free-flow speed"
        )

    levels = out[damage_col].fillna("no").astype(str).str.strip().str.lower()
    bad = ~levels.isin(_REQUIRED_STATES)
    if bad.any():
        raise ValueError(
            f"Unknown damage_state values {sorted(levels[bad].unique())}; "
            f"expected {_REQUIRED_STATES}"
        )

    if bridge_col in out.columns:
        is_bridge = out[bridge_col].astype(str).str.strip().str.lower().eq("yes")
    else:
        is_bridge = pd.Series(False, index=out.index)
    assets = np.where(is_bridge, "bridge", "road")

    factors = np.array(
        [fmap[(a, d)] for a, d in zip(assets, levels.tolist())],
        dtype=float,
    )
    out[out_col] = free_flow.to_numpy(dtype=float) * factors
    return out
