"""Geodesic length of line geometries given in a projected CRS.

Script 2 measures ``length`` in the projected CONUS frame (EPSG:9311, equal-area). Equal-area does not mean
equal-distance, so ``length_geodesic_m`` is carried beside it as an additional output and compared at the end
(``length_check_summary``). Pieces are summed segment by segment on the ellipsoid, vectorized (no per-geometry loop).

NOTE on the label: network and hazard rasters are all in EPSG:9311 (NAD27 / US National Atlas Equal Area, Clarke 1866
ellipsoid) but ``geo_runtime`` treats it as an alias of EPSG:2163 (sphere) and writes the 2163 label. The numbers are
9311 coordinates, so callers pass ``DATA_CRS`` explicitly instead of trusting ``gdf.crs``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pyproj
import shapely

DATA_CRS = "EPSG:9311"
_GEOD = pyproj.Geod(ellps="clrk66")  # NAD27 ellipsoid; Clarke 1866 coordinates from the 9311 inverse projection


def geodesic_length_m(geometries, crs=DATA_CRS) -> np.ndarray:
    """Length in metres of each line geometry, measured on the ellipsoid. NaN/None/empty geometries give 0."""
    geoms = np.asarray(geometries, dtype=object)
    out = np.zeros(len(geoms), dtype=float)
    coords, idx = shapely.get_coordinates(geoms, return_index=True)
    if len(coords) < 2:
        return out
    to_geo = pyproj.Transformer.from_crs(crs, "EPSG:4267", always_xy=True)
    lon, lat = to_geo.transform(coords[:, 0], coords[:, 1])
    same_geom = idx[1:] == idx[:-1]  # consecutive vertices of the same geometry form a segment
    _, _, dist = _GEOD.inv(lon[:-1][same_geom], lat[:-1][same_geom], lon[1:][same_geom], lat[1:][same_geom])
    np.add.at(out, idx[1:][same_geom], dist)
    return out


def length_check_summary(df: pd.DataFrame, projected_col: str = "length", geodesic_col: str = "length_geodesic_m") -> dict:
    """Projected versus geodesic length over all pieces: totals, ratio, and the worst per-piece ratios (pieces >= 1 m)."""
    p = pd.to_numeric(df[projected_col], errors="coerce")
    g = pd.to_numeric(df[geodesic_col], errors="coerce")
    ok = (p >= 1.0) & g.notna()
    ratio = (g[ok] / p[ok])
    return {
        "pieces": int(ok.sum()),
        "projected_total_m": float(p[ok].sum()),
        "geodesic_total_m": float(g[ok].sum()),
        "total_ratio": float(g[ok].sum() / p[ok].sum()) if ok.any() and p[ok].sum() > 0 else float("nan"),
        "ratio_p01": float(ratio.quantile(0.01)) if ok.any() else float("nan"),
        "ratio_p50": float(ratio.quantile(0.50)) if ok.any() else float("nan"),
        "ratio_p99": float(ratio.quantile(0.99)) if ok.any() else float("nan"),
    }
