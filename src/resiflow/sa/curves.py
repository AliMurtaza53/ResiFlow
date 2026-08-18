"""Vulnerability-curve and speed-depth transforms used as Morris SA seams.

Each function perturbs a loaded damage-ratio workbook or evaluates a
parameterized speed-depth rule, without touching the underlying source data
on disk -- callers pass a freshly-loaded DataFrame in and get a transformed
copy back.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

CURVE_PAIRS: tuple[tuple[str, str], ...] = (
    ("C1", "C2"),
    ("C3", "C4"),
    ("C5", "C6"),
)


def mix_damage_curves(df: pd.DataFrame, theta: float) -> pd.DataFrame:
    """Mix each low/high-flow curve pair toward a single blended curve.

    ``theta=0`` keeps the low-flow curve (C1/C3/C5); ``theta=1`` keeps the
    high-flow curve (C2/C4/C6); both columns of a pair are set to the same
    linear blend, ``(1 - theta) * low + theta * high``, so a downstream
    consumer reading either column of a pair sees the same mixed curve.
    Column layout (names, order) is preserved.
    """
    if not 0.0 <= theta <= 1.0:
        raise ValueError(f"theta must be in [0, 1], got {theta}")
    if "intensity" not in df.columns:
        raise KeyError("mix_damage_curves requires an 'intensity' column")

    out = df.copy()
    for low, high in CURVE_PAIRS:
        if low not in df.columns or high not in df.columns:
            raise KeyError(f"mix_damage_curves requires paired columns {low}/{high}")
        blended = (1.0 - theta) * df[low] + theta * df[high]
        out[low] = blended
        out[high] = blended
    return out


def scale_depth_axis(df: pd.DataFrame, lam: float) -> pd.DataFrame:
    """Stretch/compress the depth (intensity) axis of every curve column.

    For each recorded depth ``x``, the returned value is the *original*
    curve evaluated at ``x / lam`` (linear interpolation on the original
    grid, clamped to the grid's endpoints beyond its range). ``lam > 1``
    pushes damage onset deeper (damage at a given depth decreases);
    ``lam < 1`` pulls it shallower; ``lam == 1`` is the identity transform.
    """
    if lam <= 0:
        raise ValueError(f"lam must be positive, got {lam}")
    if "intensity" not in df.columns:
        raise KeyError("scale_depth_axis requires an 'intensity' column")

    out = df.copy()
    x = df["intensity"].to_numpy(dtype=float)
    query = x / lam
    for col in df.columns:
        if col == "intensity":
            continue
        out[col] = np.interp(query, x, df[col].to_numpy(dtype=float))
    return out


def speed_depth(vmax: float, depth_cm, threshold_cm: float, p: float = 2.0):
    """Generalized power-law speed-depth rule.

    ``V = vmax * max(0, 1 - depth / threshold) ** p``. ``p=2`` reproduces
    the Pregnolato et al. (2017) quadratic rule used by
    ``compute_maximum_speed_on_flooded_roads``; ``p=1`` is a linear
    alternative. Accepts a scalar or array-like ``depth_cm``.
    """
    if threshold_cm <= 0:
        raise ValueError(f"threshold_cm must be positive, got {threshold_cm}")
    if p <= 0:
        raise ValueError(f"p must be positive, got {p}")

    depth = np.asarray(depth_cm, dtype=float)
    frac = np.clip(1.0 - depth / threshold_cm, 0.0, None)
    result = vmax * frac**p
    return float(result) if np.ndim(depth) == 0 else result
