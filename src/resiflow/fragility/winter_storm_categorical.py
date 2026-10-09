"""Winter storm / snow categorical fragility: snow depth (mm) -> damage level.

ONE classification shared by ``winter_storm`` and ``snow`` (``snow_categorical``
delegates here). Depth-primary, with two independent one-tier escalators that
only apply once depth alone has already reached "moderate"::

    base tier (depth only, VDOT ladder)
        depth <= 0 or NaN         -> no
        depth <  102 mm           -> minor
        102 <= depth <  305 mm    -> moderate
        305 <= depth <  457 mm    -> extensive
        depth >= 457 mm           -> severe
    gate        escalators apply only when base tier >= moderate (depth >= 102 mm);
                below the gate the tier is depth-only, whatever duration/temperature say
    escalators  +1 tier if duration_hours >= 24
                +1 tier if T_factor >= 1.5 (air_temp_F <= 10 F, T32's own T_factor)
                independent, stacking, capped at severe
    missing     NaN / absent duration or temperature = no escalation

Why gated: an ungated version pushed 31-37% of sub-102 mm links on Uri/Elliott
to extensive/severe purely on duration/temperature, i.e. depth was primary in
name only. The T_factor >= 1.5 escalator IS the winter ice-event handling
(``parameters/tables/T32_ice_event_assumption_note.csv`` is documentation of
that choice, not a separate code path).

This replaces both the flat depth-only placeholders that lived here and in
``snow_categorical.py``. It deliberately does NOT reuse T32's ``passes``
scalar (MAX(depth/d_plow, duration/cycle)): MAX-blending is fine for a
continuous cost, but for a categorical tier it let the coarse duration proxy
(0/24/48 h) dominate depth. ``winter_storm_cost.py`` is untouched.

Known data limits (unchanged by this function): ``duration_hours`` is a
24-hour-granularity SNODAS depth-delta proxy (only 0/24/48), and
``air_temp_F`` is PRISM daily tmin, which runs cold versus storm-hour temperature.
The 102/305/457 mm ladder boundaries are the project's VDOT ladder as specified
for this work; a primary citation still needs to be attached.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from resiflow.hazards.winter_storm_cost import _load_t32_coefficients

DEPTH_LADDER_MM = (102.0, 305.0, 457.0)  # minor -> moderate -> extensive -> severe
ESCALATION_GATE_MM = DEPTH_LADDER_MM[0]  # base tier >= moderate
DURATION_ESCALATOR_HOURS = 24.0
T_FACTOR_ESCALATOR = 1.5

LEVELS = ("no", "minor", "moderate", "extensive", "severe")
_MODERATE = 2
_SEVERE = 4


def t_factor_from_air_temp_f(air_temp_f: pd.Series | np.ndarray | None, *, length: int | None = None) -> np.ndarray:
    """T32's T_factor = MIN(T_cap, 1 + T_slope * MAX(0, T_ref - air_temp_F)); NaN stays NaN."""
    if air_temp_f is None:
        return np.full(length or 0, np.nan)
    coeffs = _load_t32_coefficients()
    temp = pd.to_numeric(pd.Series(air_temp_f), errors="coerce").to_numpy(dtype=float)
    return np.minimum(coeffs["T_cap"], 1.0 + coeffs["T_slope"] * np.maximum(0.0, coeffs["T_ref"] - temp))


def _damage_tier(depth: np.ndarray, duration: np.ndarray, t_factor: np.ndarray) -> np.ndarray:
    base = np.where(
        depth > 0,
        1 + (depth >= DEPTH_LADDER_MM[0]).astype(int) + (depth >= DEPTH_LADDER_MM[1]).astype(int)
        + (depth >= DEPTH_LADDER_MM[2]).astype(int),
        0,
    )
    gated = base >= _MODERATE
    # NaN comparisons are False -> a missing input never escalates.
    with np.errstate(invalid="ignore"):
        escalation = (duration >= DURATION_ESCALATOR_HOURS).astype(int) + (t_factor >= T_FACTOR_ESCALATOR).astype(int)
    return np.minimum(_SEVERE, base + np.where(gated, escalation, 0))


def compute_damage_levels_vectorized(
    road_classification: pd.Series,
    snow_depth_mm: pd.Series,
    road_label: pd.Series | None = None,  # noqa: ARG001 -- interface parity with the shared categorical_fn signature
    *,
    duration_hours: pd.Series | None = None,
    air_temp_f: pd.Series | None = None,
) -> pd.Series:
    """Damage level per row. ``road_classification``/``road_label`` are accepted for
    interface parity only -- the ladder is not road-class dependent."""
    index = snow_depth_mm.index
    depth = pd.to_numeric(snow_depth_mm, errors="coerce").fillna(0.0).to_numpy(dtype=float)
    duration = (
        pd.to_numeric(duration_hours, errors="coerce").reindex(index).to_numpy(dtype=float)
        if duration_hours is not None
        else np.full(len(depth), np.nan)
    )
    t_factor = (
        t_factor_from_air_temp_f(air_temp_f.reindex(index), length=len(depth))
        if air_temp_f is not None
        else np.full(len(depth), np.nan)
    )
    tiers = _damage_tier(depth, duration, t_factor)
    return pd.Series(np.array(LEVELS, dtype=object)[tiers], index=index, dtype=object)
