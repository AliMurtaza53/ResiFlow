"""Synthetic hazard intensity field generators (rasters only; no fragility)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.features import rasterize
from rasterio.transform import Affine, from_origin
from shapely.geometry import LineString, Point


@dataclass(frozen=True)
class SyntheticRaster:
    """In-memory intensity field suitable for exposure sampling."""

    data: np.ndarray
    transform: Affine
    crs: str
    nodata: float = -9999.0
    intensity_unit: str = "m_depth"

    def write_geotiff(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        profile = {
            "driver": "GTiff",
            "height": self.data.shape[0],
            "width": self.data.shape[1],
            "count": 1,
            "dtype": "float32",
            "crs": self.crs,
            "transform": self.transform,
            "nodata": self.nodata,
        }
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(self.data.astype("float32"), 1)
        return path


def _grid_for_links(
    links: gpd.GeoDataFrame,
    *,
    resolution_m: float,
    pad_m: float = 500.0,
) -> tuple[float, float, float, float, int, int, Affine]:
    minx, miny, maxx, maxy = links.total_bounds
    minx -= pad_m
    miny -= pad_m
    maxx += pad_m
    maxy += pad_m
    width = max(1, int(np.ceil((maxx - minx) / resolution_m)))
    height = max(1, int(np.ceil((maxy - miny) / resolution_m)))
    transform = from_origin(minx, maxy, resolution_m, resolution_m)
    return minx, miny, maxx, maxy, width, height, transform


def bridge_interior(
    links: gpd.GeoDataFrame,
    flooded_edge_ids: Sequence[str],
    *,
    peak_intensity: float,
    resolution_m: float = 10.0,
    interior_fraction: tuple[float, float] = (0.35, 0.65),
    crs: str | None = None,
) -> SyntheticRaster:
    """Rasterize bridge interior segments (Sioux Falls default pattern)."""
    flooded = links.loc[links["e_id"].isin(flooded_edge_ids)]
    if flooded.empty:
        raise ValueError("No links matched flooded_edge_ids for bridge_interior")

    _, _, _, _, width, height, transform = _grid_for_links(links, resolution_m=resolution_m)
    start_frac, end_frac = interior_fraction
    buffer_m = resolution_m * 0.5
    shapes = []
    for geom in flooded.geometry:
        start = geom.interpolate(start_frac, normalized=True)
        end = geom.interpolate(end_frac, normalized=True)
        interior = LineString([(start.x, start.y), (end.x, end.y)])
        shapes.append((interior.buffer(buffer_m), peak_intensity))

    data = rasterize(
        shapes,
        out_shape=(height, width),
        transform=transform,
        fill=0.0,
        all_touched=True,
    )
    out_crs = crs or (str(links.crs) if links.crs is not None else "EPSG:4326")
    return SyntheticRaster(data=data, transform=transform, crs=out_crs)


def gaussian_hotspot(
    links: gpd.GeoDataFrame,
    center: tuple[float, float],
    *,
    sigma_m: float,
    peak_intensity: float,
    resolution_m: float = 10.0,
    crs: str | None = None,
) -> SyntheticRaster:
    """Localized Gaussian intensity field around a map coordinate."""
    _, _, _, _, width, height, transform = _grid_for_links(links, resolution_m=resolution_m)
    cx, cy = center
    rows, cols = np.mgrid[0:height, 0:width]
    xs = transform.c + cols * transform.a
    ys = transform.f + rows * transform.e
    dist2 = (xs - cx) ** 2 + (ys - cy) ** 2
    data = peak_intensity * np.exp(-dist2 / (2.0 * sigma_m**2))
    out_crs = crs or (str(links.crs) if links.crs is not None else "EPSG:4326")
    return SyntheticRaster(data=data, transform=transform, crs=out_crs)


def linear_corridor(
    links: gpd.GeoDataFrame,
    start: tuple[float, float],
    end: tuple[float, float],
    *,
    peak_intensity: float,
    corridor_width_m: float = 200.0,
    resolution_m: float = 10.0,
    crs: str | None = None,
) -> SyntheticRaster:
    """Corridor intensity along a straight line between two points."""
    _, _, _, _, width, height, transform = _grid_for_links(links, resolution_m=resolution_m)
    corridor = LineString([start, end]).buffer(corridor_width_m / 2.0)
    data = rasterize(
        [(corridor, peak_intensity)],
        out_shape=(height, width),
        transform=transform,
        fill=0.0,
        all_touched=True,
    )
    out_crs = crs or (str(links.crs) if links.crs is not None else "EPSG:4326")
    return SyntheticRaster(data=data, transform=transform, crs=out_crs)


def snow_band(
    links: gpd.GeoDataFrame,
    *,
    center_y: float,
    band_width_m: float,
    peak_intensity_mm: float,
    resolution_m: float = 10.0,
    crs: str | None = None,
) -> SyntheticRaster:
    """Latitudinal snow band (intensity in mm)."""
    minx, miny, maxx, maxy, width, height, transform = _grid_for_links(links, resolution_m=resolution_m)
    band = LineString([(minx, center_y), (maxx, center_y)]).buffer(band_width_m / 2.0)
    data = rasterize(
        [(band, peak_intensity_mm)],
        out_shape=(height, width),
        transform=transform,
        fill=0.0,
        all_touched=True,
    )
    out_crs = crs or (str(links.crs) if links.crs is not None else "EPSG:4326")
    return SyntheticRaster(
        data=data,
        transform=transform,
        crs=out_crs,
        intensity_unit="mm_snow",
    )


def random_failures(
    links: gpd.GeoDataFrame,
    *,
    failure_fraction: float,
    peak_intensity: float,
    seed: int = 0,
    resolution_m: float = 10.0,
    crs: str | None = None,
) -> SyntheticRaster:
    """Stress-test raster with random link interior hotspots."""
    if not 0.0 < failure_fraction <= 1.0:
        raise ValueError("failure_fraction must be in (0, 1]")
    rng = np.random.default_rng(seed)
    n_fail = max(1, int(round(len(links) * failure_fraction)))
    chosen = links.sample(n=min(n_fail, len(links)), random_state=seed)
    _, _, _, _, width, height, transform = _grid_for_links(links, resolution_m=resolution_m)
    buffer_m = resolution_m * 0.5
    shapes = []
    for geom in chosen.geometry:
        mid = geom.interpolate(0.5, normalized=True)
        shapes.append((Point(mid.x, mid.y).buffer(buffer_m), peak_intensity))
    data = rasterize(
        shapes,
        out_shape=(height, width),
        transform=transform,
        fill=0.0,
        all_touched=True,
    )
    out_crs = crs or (str(links.crs) if links.crs is not None else "EPSG:4326")
    return SyntheticRaster(data=data, transform=transform, crs=out_crs)


def resolve_synthetic_generator(name: str):
    """Map config source strings like ``synthetic:bridge_interior`` to callables."""
    key = name.split(":", 1)[-1].strip().lower()
    registry = {
        "bridge_interior": bridge_interior,
        "gaussian_hotspot": gaussian_hotspot,
        "linear_corridor": linear_corridor,
        "river_corridor": linear_corridor,
        "snow_band": snow_band,
        "random_failures": random_failures,
    }
    if key not in registry:
        raise ValueError(f"Unknown synthetic generator: {name}. Options: {sorted(registry)}")
    return registry[key]
