"""Winter storm direct cleanup cost -- real DOT-regression formula, T32.

Replaces the flood-shim direct-cost path for winter_storm (snow depth mm /
1000 repackaged as a fake flood depth, then priced with FLOOD's damage-ratio/
damage-cost workbooks -- confirmed independently wrong by 150-1000x vs. real
Jonas damage estimates, see scripts/3_damage_analysis.py's calculate_damage()
docstring and results/finale_2026_08/build_finale_figures.py's
WINTER_STORM_EXCLUSION note).

Formula (``parameters/tables/T32_winter_storm_direct_cost_function.csv``,
MnDOT/WisDOT/MDOT-cited regression coefficients)::

    C = [kappa + c_pass * passes] * T_factor   (USD per lane-mile per event)
    passes = MAX(snow_depth_mm / d_plow_mm, duration_hours / cycle_hours)
    T_factor = MIN(T_cap, 1 + T_slope * MAX(0, T_ref - air_temp_F))

T32's own CSV is NOT a single rectangular table (it stacks a coefficient
block, 5 worked examples, and input-source citations under different
column counts in one file, by design -- see its own header) -- so this
module parses the coefficient block directly with ``csv.reader`` rather than
``resiflow.tables.load_table`` (which assumes one axis-column table and would
silently misread the worked-examples/citation rows as more coefficient
data). The 5 worked examples are reproduced exactly by
``winter_storm_direct_cost_usd_per_lane_mile`` -- see
tests/test_winter_storm_cost.py.

``duration_hours``/``air_temp_F`` per event/link are sourced from real, but
approximate, data (see scripts/prepare_winter_storm_duration_temp.py):
duration_hours from consecutive-day SNODAS depth deltas (24h granularity,
NOT the ideal 6-hr NOHRSC snowfall-analysis grid T32's own header cites --
that product's historical archive wasn't readily available for these events
within scope) and air_temp_F from PRISM daily tmin (a real, per-event,
per-pixel value, but the day's MINIMUM rather than a storm-hour-specific
reading). Missing duration/temperature on a given segment does not fabricate
a value -- see the function's own fallbacks, documented inline.
"""

from __future__ import annotations

import csv
import math
from functools import lru_cache
from pathlib import Path

from resiflow.tables import tables_root

_TABLE_NAME = "T32_winter_storm_direct_cost_function.csv"
_COEFFICIENT_NAMES = ("kappa", "c_pass", "d_plow_mm", "cycle_hours", "T_ref", "T_slope", "T_cap")

# T32's own class-multiplier definition (its CSV header, "class multiplier"
# row) -- major INCLUDES secondary, unlike hazus_bridge.py's
# _MAJOR_ROAD_CLASSIFICATIONS (which does not). Kept as its own set
# deliberately, not reused, to avoid silently conflating two different
# HAZUS-vs-DOT road-tier schemes.
_T32_MAJOR_ROAD_CLASSIFICATIONS = {"motorway", "motorway_link", "trunk", "primary", "secondary"}
_MAJOR_MULTIPLIER = 2.00
_MINOR_MULTIPLIER = 0.85


def _strip_quotes(cell: str) -> str:
    cell = cell.strip()
    if len(cell) >= 2 and cell[0] == '"' and cell[-1] == '"':
        cell = cell[1:-1]
    return cell


@lru_cache(maxsize=1)
def _load_t32_coefficients(params_root: str | None = None) -> dict[str, float]:
    path = Path(tables_root(params_root)) / _TABLE_NAME
    coefficients: dict[str, float] = {}
    with path.open(newline="", encoding="utf-8") as fh:
        for raw_row in csv.reader(fh):
            if not raw_row:
                continue
            first = _strip_quotes(raw_row[0])
            if first.startswith("#") or not first:
                continue
            if first in _COEFFICIENT_NAMES and len(raw_row) >= 2:
                coefficients[first] = float(raw_row[1])
    missing = set(_COEFFICIENT_NAMES) - coefficients.keys()
    if missing:
        raise ValueError(f"{_TABLE_NAME}: missing coefficient rows {sorted(missing)}")
    return coefficients


def _road_class_multiplier(road_classification: str | None) -> float:
    normalized = str(road_classification or "").strip().lower()
    return _MAJOR_MULTIPLIER if normalized in _T32_MAJOR_ROAD_CLASSIFICATIONS else _MINOR_MULTIPLIER


def winter_storm_direct_cost_usd_per_lane_mile(
    *,
    snow_depth_mm: float | None,
    duration_hours: float | None,
    air_temp_F: float | None,
    road_classification: str | None,
) -> float:
    """T32's direct cleanup cost formula, USD per lane-mile per event.

    ``duration_hours=None`` falls back to the depth-only floor of ``passes``
    (``snow_depth_mm/d_plow_mm``) -- a real lower bound, not an invented
    duration. ``air_temp_F=None`` falls back to ``T_factor=1.0`` (no
    cold-weather cleanup penalty applied) -- conservative-low, not a guess at
    the actual temperature. Both are documented fallbacks for real, but
    incomplete, per-event coverage (see module docstring), never used when
    the real value is available.
    """
    if snow_depth_mm is None or (isinstance(snow_depth_mm, float) and math.isnan(snow_depth_mm)) or snow_depth_mm <= 0:
        return 0.0

    coeffs = _load_t32_coefficients()

    passes = snow_depth_mm / coeffs["d_plow_mm"]
    if duration_hours is not None and not (isinstance(duration_hours, float) and math.isnan(duration_hours)):
        passes = max(passes, float(duration_hours) / coeffs["cycle_hours"])

    if air_temp_F is None or (isinstance(air_temp_F, float) and math.isnan(air_temp_F)):
        t_factor = 1.0
    else:
        t_factor = min(coeffs["T_cap"], 1.0 + coeffs["T_slope"] * max(0.0, coeffs["T_ref"] - float(air_temp_F)))

    cost_per_lane_mile = (coeffs["kappa"] + coeffs["c_pass"] * passes) * t_factor
    return cost_per_lane_mile * _road_class_multiplier(road_classification)


__all__ = ["winter_storm_direct_cost_usd_per_lane_mile"]
