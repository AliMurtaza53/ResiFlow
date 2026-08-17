"""Flood operational fragility: intensity to max_speed."""

from __future__ import annotations

import numpy as np
import pandas as pd

from resiflow.parameters import get_parameter

_FLOOD_CLOSURE_THRESHOLD_DEFAULT = get_parameter(
    "hazard_disruption", "flood_closure_threshold_cm", 30
)
# Exponent p of the generalized speed-depth rule V = V_max * (1 - d/d_c)**p.
# p=2 is the historical Pregnolato quadratic; p=1 the linear alternate.
# SA seam (see resiflow.sa.curves.speed_depth); default keeps behavior
# unchanged without overrides.
_SPEED_DEPTH_EXPONENT_DEFAULT = float(
    get_parameter("hazard_disruption", "speed_depth_exponent", 2.0)
)


def _use_table_speed_depth() -> bool:
    """Flag: read V/Vmax from the discretized T19 table instead of the formula.

    Read at call time (the parameter loader is cached) so per-run overrides
    take effect without re-importing the module. Default False keeps the
    closed-form path — a no-flag run is bit-identical to current behavior.
    """
    return bool(get_parameter("hazard_disruption", "use_table_speed_depth", False))


def _speed_depth_ratio_from_table(depth_cm, threshold_cm: float):
    """V/Vmax interpolated from the T19 column for this closure threshold.

    The table discretizes the p=2 (Pregnolato) curve only; if a non-default
    speed_depth_exponent is also set, the table wins and a warning is logged.
    """
    from resiflow.tables import interpolate, load_table

    if _SPEED_DEPTH_EXPONENT_DEFAULT != 2.0:
        import logging

        logging.getLogger(__name__).warning(
            "use_table_speed_depth overrides speed_depth_exponent=%s: the "
            "discretized T19 curve encodes the p=2 quadratic.",
            _SPEED_DEPTH_EXPONENT_DEFAULT,
        )
    table = load_table(
        get_parameter(
            "hazard_disruption", "speed_depth_table", "T19_speed_depth_curve_discretized"
        )
    )
    column = f"v_ratio_xd{int(round(threshold_cm))}"
    if column not in table.columns:
        raise ValueError(
            f"Speed-depth table has no column {column!r} for closure threshold "
            f"{threshold_cm} cm (available: {list(table.columns)[1:]})."
        )
    return interpolate(table, depth_cm, column, axis_column="flood_depth_cm")


def compute_maximum_speed_on_flooded_roads(
    depth: float,
    free_flow_speed: float,
    threshold: float = _FLOOD_CLOSURE_THRESHOLD_DEFAULT,
) -> float:
    """
    Calculates the maximum allowable speed on flooded roads based on flood depth.

    Parameters:
        depth (float): Flood depth in meters.
        free_flow_speed (float): Free-flow speed under normal conditions (mph).
        threshold (float, optional): Depth threshold in centimeters for road closure
            (default is 30 cm).

    Returns:
        float: Maximum speed on the flooded road in miles per hour (mph).
    """

    depth = depth * 100  # m to cm
    if depth < threshold:  # cm
        if _use_table_speed_depth():
            return free_flow_speed * _speed_depth_ratio_from_table(depth, threshold)
        p = _SPEED_DEPTH_EXPONENT_DEFAULT
        if p == 2.0:
            # keep the historical expression exactly (bit-identical baseline)
            value = free_flow_speed * (depth / threshold - 1) ** 2  # mph
        else:
            value = free_flow_speed * (1 - depth / threshold) ** p  # mph
        return value  # mph
    else:
        return 0.0  # mph

def apply_max_speed_to_links(
    road_links: pd.DataFrame,
    *,
    depth_key: int,
    depth_col: str = "flood_depth_max",
    free_flow_col: str = "free_flow_speeds",
    out_col: str = "max_speed",
) -> pd.DataFrame:
    """Vectorized speed cap using the Script 2 closure rule (depth_key in cm)."""
    out = road_links.copy()
    if depth_col not in out.columns:
        out[depth_col] = 0.0
    out[depth_col] = out[depth_col].fillna(0.0)
    if free_flow_col not in out.columns:
        out[free_flow_col] = 50.0
    out[free_flow_col] = out[free_flow_col].fillna(50.0)
    flood_depth_cm = pd.to_numeric(out[depth_col], errors="coerce") * 100.0
    free_flow_speed = pd.to_numeric(out[free_flow_col], errors="coerce")
    p = _SPEED_DEPTH_EXPONENT_DEFAULT
    if _use_table_speed_depth():
        reduced = free_flow_speed * _speed_depth_ratio_from_table(
            flood_depth_cm.to_numpy(dtype=float), depth_key
        )
    elif p == 2.0:
        # keep the historical expression exactly (bit-identical baseline)
        reduced = free_flow_speed * ((flood_depth_cm / depth_key - 1) ** 2)
    else:
        reduced = free_flow_speed * (
            (1.0 - flood_depth_cm / depth_key).clip(lower=0.0) ** p
        )
    out[out_col] = np.where(flood_depth_cm < depth_key, reduced, 0.0)
    return out
