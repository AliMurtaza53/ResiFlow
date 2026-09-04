from __future__ import annotations

from typing import Iterable, Tuple

import numpy as np


CurvePoints = Tuple[np.ndarray, np.ndarray]


def _as_xy(curve: Iterable[Tuple[float, float]]) -> CurvePoints:
    arr = np.asarray(list(curve), dtype=float)
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError("curve must be an iterable of (depth, damage) pairs")
    x = arr[:, 0]
    y = arr[:, 1]
    order = np.argsort(x)
    return x[order], y[order]


def scale_depth_axis(curve: Iterable[Tuple[float, float]], factor: float) -> CurvePoints:
    """Scale depth coordinates by ``factor`` while preserving damages."""
    if factor <= 0:
        raise ValueError("factor must be positive")
    x, y = _as_xy(curve)
    return x * float(factor), y


def mix_damage_curves(
    curve_a: Iterable[Tuple[float, float]],
    curve_b: Iterable[Tuple[float, float]],
    weight_a: float,
) -> CurvePoints:
    """Mix two damage curves by weighted averaging over a shared depth grid."""
    if not 0 <= weight_a <= 1:
        raise ValueError("weight_a must be in [0, 1]")
    xa, ya = _as_xy(curve_a)
    xb, yb = _as_xy(curve_b)

    x = np.unique(np.concatenate([xa, xb]))
    ya_i = np.interp(x, xa, ya, left=ya[0], right=ya[-1])
    yb_i = np.interp(x, xb, yb, left=yb[0], right=yb[-1])
    y = weight_a * ya_i + (1.0 - weight_a) * yb_i
    return x, y


def speed_depth(depth: float | np.ndarray, free_flow_speed: float = 1.0, max_depth: float = 1.0) -> float | np.ndarray:
    """Return speed multiplier that decays linearly with water depth.

    At depth ``0`` multiplier is ``free_flow_speed`` and at ``max_depth`` it is ``0``.
    Values are clipped to ``[0, free_flow_speed]``.
    """
    if free_flow_speed < 0:
        raise ValueError("free_flow_speed must be non-negative")
    if max_depth <= 0:
        raise ValueError("max_depth must be positive")

    values = np.asarray(depth, dtype=float)
    multiplier = free_flow_speed * (1.0 - (values / max_depth))
    clipped = np.clip(multiplier, 0.0, free_flow_speed)
    if np.isscalar(depth):
        return float(clipped)
    return clipped
