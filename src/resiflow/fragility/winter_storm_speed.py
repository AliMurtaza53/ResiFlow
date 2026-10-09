"""Winter storm / snow operational fragility: ambient snow depth (mm) -> max_speed.

Replaces the flood-shaped quadratic V = V0 * (d/k - 1)^2 (k = 100 mm winter
storm, 150 mm snow -- both unsourced) that used to live in
``winter_storm_operational.py`` / ``snow_operational.py``. The speed ratio now
comes from ``parameters/tables/T19_winter_speed_closure_crosswalk.csv`` (the
table written as that replacement), interpolated on depth, passenger-car column.

READ THIS BEFORE RELYING ON IT -- what T19-winter is and is not:
  * It is a CROSSWALK from McBride (1978) pavement states onto SNODAS depth
    bins, not a sourced depth-speed curve (its own header says so).
  * It is "what speed is supportable at this ambient depth if driven on now".
    Whether a link is open at all is T33/T34's job (``day_open``), and
    post-plow recovery is T35's -- neither is folded in here.
  * The table reaches 0.00 at >= 254 mm, so this function closes a link
    (max_speed = 0) there for EVERY road class. T19's own closure notes say
    closure on major/plowed roads is operational (visibility/wind), not
    depth-triggered, and that rank 4-5 depth closure (200-250 mm) is to be a
    one-time flag, not a dynamic gate. Making the speed curve rank-aware is an
    open design decision; see ``winter_storm_clearance.py`` for the flag.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from resiflow.tables import tables_root

_TABLE_NAME = "T19_winter_speed_closure_crosswalk.csv"
_HEADER_FIRST_CELL = "snow_depth_mm"


@lru_cache(maxsize=1)
def load_speed_ratio_curve(params_root: str | None = None) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(depth_mm, v_ratio_car, v_ratio_truck) from T19-winter's first (speed-ratio) block.

    The CSV stacks a speed-ratio block and a closure-threshold block under
    different column counts, so it is parsed with ``csv.reader`` up to the
    first ``#`` row after the header (same approach as T32's parser).
    """
    path = Path(tables_root(params_root)) / _TABLE_NAME
    depth, car, truck = [], [], []
    in_block = False
    with path.open(newline="", encoding="utf-8") as fh:
        for row in csv.reader(fh):
            if not row:
                continue
            first = row[0].strip()
            if not in_block:
                in_block = first == _HEADER_FIRST_CELL
                continue
            if first.startswith("#"):
                break
            depth.append(float(first))
            car.append(float(row[3]))
            truck.append(float(row[4]))
    if not depth:
        raise ValueError(f"{_TABLE_NAME}: no speed-ratio rows found")
    order = np.argsort(depth)
    return np.asarray(depth)[order], np.asarray(car)[order], np.asarray(truck)[order]


def speed_ratio(depth_mm: pd.Series | np.ndarray, *, vehicle: str = "car") -> np.ndarray:
    """V/V0 interpolated on depth; depth beyond the last tabulated row holds that row's value."""
    xs, car, truck = load_speed_ratio_curve()
    ys = car if vehicle == "car" else truck
    depth = pd.to_numeric(pd.Series(depth_mm), errors="coerce").fillna(0.0).to_numpy(dtype=float)
    return np.interp(np.maximum(depth, 0.0), xs, ys)


def apply_max_speed_to_links(
    road_links: pd.DataFrame,
    *,
    depth_col: str,
    free_flow_col: str = "free_flow_speeds",
    out_col: str = "max_speed",
    vehicle: str = "car",
) -> pd.DataFrame:
    """Vectorized speed cap from ambient snow depth (mm) via the T19-winter ratio curve."""
    out = road_links.copy()
    if depth_col not in out.columns:
        out[depth_col] = 0.0
    depth = pd.to_numeric(out[depth_col], errors="coerce").fillna(0.0)
    if free_flow_col not in out.columns:
        out[free_flow_col] = 50.0
    free_flow = pd.to_numeric(out[free_flow_col], errors="coerce").fillna(50.0)
    out[free_flow_col] = free_flow
    out[out_col] = free_flow.to_numpy(dtype=float) * speed_ratio(depth, vehicle=vehicle)
    return out
