"""FHWA National Highway Construction Cost Index (NHCCI) dollar-year harmonization.

Source: parameters/tables/NHCCI_20260922.csv, FHWA's quarterly NHCCI series
(overall composite index, base = 1.0 at 2003 Q1, plus group-level percent-
change sub-indices by construction item). Used to escalate/deflate real
sourced unit costs that were published in different base years -- T24 CP25
(2018 USD), T30 (2024 USD), and the Rostami et al. tunnel model (December
2008 USD) -- onto one common dollar-year, per explicit decision 2026-10-08
(see docs/FLOOD_TABLE_REVIEW.md). Where NHCCI doesn't apply (it covers
highway construction broadly; there is no construction-specific CPI series
in this project to fall back to, and none was needed -- all three source
years are within NHCCI's 2003 Q1-present coverage), it is not substituted.

The SEASONALLY ADJUSTED composite ("NHCCI-Seasonally-Adjusted") is used
rather than the raw series: escalation factors here compare specific
quarters that are usually NOT the same calendar quarter (e.g. 2018 Q4 to
2026 Q1), so removing seasonal noise avoids biasing the ratio.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

_TABLE_NAME = "NHCCI_20260922"
_QUARTER_RE = re.compile(r"^\s*(\d{4})\s*Q([1-4])\s*$")


def load_nhcci(params_root: Path | str | None = None) -> pd.DataFrame:
    from resiflow.tables import load_table

    table = load_table(_TABLE_NAME, params_root=params_root)
    parsed = table["quarter"].str.extract(_QUARTER_RE)
    out = table.copy()
    out["year"] = parsed[0].astype(int)
    out["q"] = parsed[1].astype(int)
    return out


def nhcci_index(
    year: int,
    quarter: int,
    *,
    seasonally_adjusted: bool = True,
    params_root: Path | str | None = None,
) -> float:
    """The NHCCI composite index level for one real quarter (not a percent change)."""
    table = load_nhcci(params_root=params_root)
    column = "NHCCI-Seasonally-Adjusted" if seasonally_adjusted else "NHCCI"
    row = table.loc[(table["year"] == year) & (table["q"] == quarter)]
    if row.empty:
        known_range = (table["year"].min(), table["q"].iloc[0]), (
            table["year"].max(),
            table["q"].iloc[-1],
        )
        raise ValueError(
            f"NHCCI has no {year} Q{quarter} row; table covers {known_range[0]} to {known_range[1]}"
        )
    return float(row.iloc[0][column])


def latest_quarter(params_root: Path | str | None = None) -> tuple[int, int]:
    """The most recent (year, quarter) NHCCI publishes -- the default
    harmonization target: the best available approximation of "today's
    dollars", and not an arbitrarily chosen future year."""
    table = load_nhcci(params_root=params_root)
    last = table.sort_values(["year", "q"]).iloc[-1]
    return int(last["year"]), int(last["q"])


def escalation_factor(
    from_year: int,
    from_quarter: int,
    to_year: int | None = None,
    to_quarter: int | None = None,
    *,
    seasonally_adjusted: bool = True,
    params_root: Path | str | None = None,
) -> float:
    """Multiply a cost in ``from_year`` Q``from_quarter`` dollars by this
    factor to get it in ``to_year`` Q``to_quarter`` dollars (default: the
    latest available NHCCI quarter)."""
    if to_year is None or to_quarter is None:
        to_year, to_quarter = latest_quarter(params_root=params_root)
    from_index = nhcci_index(
        from_year, from_quarter, seasonally_adjusted=seasonally_adjusted, params_root=params_root
    )
    to_index = nhcci_index(
        to_year, to_quarter, seasonally_adjusted=seasonally_adjusted, params_root=params_root
    )
    return to_index / from_index
