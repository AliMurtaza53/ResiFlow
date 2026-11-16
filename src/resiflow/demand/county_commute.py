"""County-specific jobs -> vehicle trips from ACS B08301 (see scripts/commute_occupancy_acs.py).

LODES counts JOBS, including people who work from home that day. The factor that converts
jobs to car trips is therefore vehicles per ALL worker (``vehicles_per_all_worker``), not
vehicles per commuting worker (that one would treat home workers as commuters).
One direction only: no round-trip doubling (owner decision 2026-11-15).
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def load_county_factors(path: str | Path, column: str = "vehicles_per_all_worker") -> dict[str, float]:
    """Return {5-digit county FIPS: vehicles per job} from the script's commute_params.json."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return {fips: float(rec[column]) for fips, rec in data["counties"].items() if rec.get(column) is not None}


def convert_od_by_home_county(
    od: pd.DataFrame,
    node_to_county: dict[str, str],
    factors: dict[str, float],
    fallback: float,
    flow_col: str = "Car21",
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Scale each row by the factor of its ORIGIN (home) county; unknown counties use ``fallback``."""
    out = od.copy()
    county = out["origin_node"].astype(str).map(node_to_county)
    f = county.map(factors)
    missing = float(f.isna().sum())
    out[flow_col] = out[flow_col] * f.fillna(fallback)
    return out, {"rows_using_fallback": missing, "jobs_in": float(od[flow_col].sum()), "vehicles_out": float(out[flow_col].sum())}
