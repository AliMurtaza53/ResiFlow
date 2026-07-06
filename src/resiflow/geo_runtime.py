"""Portable GDAL/PROJ setup and CONUS CRS normalization for raster-vector work."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union

import geopandas as gpd
import numpy as np
import pyproj
import rasterio
from rasterio import windows as rio_windows
from rasterio.warp import Resampling, calculate_default_transform, reproject
from shapely.geometry import box
from snail import intersection

CONUS_TARGET_CRS = "EPSG:2163"

_US_NATIONAL_ATLAS_MARKERS = (
    "US National Atlas Equal Area",
    "EPSG:2163",
    "ESRI:102008",
    "102008",
)

_CONFIGURED = False
_RUNTIME_STATUS: Dict[str, Optional[str]] = {
    "gdal_data": None,
    "proj_data": None,
    "proj_lib": None,
}


def _valid_data_dir(path: Path, marker: str) -> bool:
    return path.is_dir() and (path / marker).exists()


def _candidate_geo_dirs() -> list[Path]:
    candidates: list[Path] = []
    prefix = Path(sys.prefix)
    candidates.extend(
        [
            prefix / "Library" / "share" / "gdal",
            prefix / "share" / "gdal",
            prefix / "Library" / "share" / "proj",
            prefix / "share" / "proj",
        ]
    )
    try:
        import rasterio as _rasterio

        candidates.append(Path(_rasterio.__file__).resolve().parent / "proj_data")
    except Exception:
        pass
    try:
        proj_data_dir = pyproj.datadir.get_data_dir()
        if proj_data_dir:
            candidates.append(Path(proj_data_dir))
    except Exception:
        pass
    for key in ("GDAL_DATA", "PROJ_DATA", "PROJ_LIB"):
        val = os.environ.get(key)
        if val:
            candidates.append(Path(val))
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path)
        if key not in seen:
            seen.add(key)
            deduped.append(path)
    return deduped


def configure_geo_runtime(force: bool = False) -> Dict[str, Optional[str]]:
    """Configure GDAL_DATA and PROJ_DATA from the active Python environment."""
    global _CONFIGURED, _RUNTIME_STATUS
    if _CONFIGURED and not force:
        return dict(_RUNTIME_STATUS)

    gdal_dir = os.environ.get("GDAL_DATA")
    proj_dir = os.environ.get("PROJ_DATA") or os.environ.get("PROJ_LIB")

    if not gdal_dir or not Path(gdal_dir).is_dir():
        for path in _candidate_geo_dirs():
            if _valid_data_dir(path, "gdalvrt.xsd") or _valid_data_dir(path, "gdalinfo.exe"):
                gdal_dir = str(path)
                break
            if path.name.lower() == "gdal" and path.is_dir():
                gdal_dir = str(path)

    if not proj_dir or not _valid_data_dir(Path(proj_dir), "proj.db"):
        for path in _candidate_geo_dirs():
            if _valid_data_dir(path, "proj.db"):
                proj_dir = str(path)
                break

    if gdal_dir:
        os.environ["GDAL_DATA"] = gdal_dir
    if proj_dir:
        os.environ["PROJ_DATA"] = proj_dir
        os.environ["PROJ_LIB"] = proj_dir
        try:
            pyproj.datadir.set_data_dir(proj_dir)
        except Exception:
            pass

    _RUNTIME_STATUS = {
        "gdal_data": os.environ.get("GDAL_DATA"),
        "proj_data": os.environ.get("PROJ_DATA"),
        "proj_lib": os.environ.get("PROJ_LIB"),
    }
    _CONFIGURED = True

    if gdal_dir:
        logging.info("Using GDAL_DATA: %s", gdal_dir)
    else:
        logging.warning(
            "Could not locate GDAL_DATA. See docs/geo_projection_conus.md for setup."
        )
    if proj_dir:
        logging.info("Using PROJ_DATA: %s", proj_dir)
    else:
        logging.warning(
            "Could not locate PROJ_DATA. See docs/geo_projection_conus.md for setup."
        )
    return dict(_RUNTIME_STATUS)


def get_geo_runtime_status() -> Dict[str, Optional[str]]:
    """Return resolved GDAL/PROJ paths for troubleshooting."""
    if not _CONFIGURED:
        configure_geo_runtime()
    return dict(_RUNTIME_STATUS)


def rasterio_env() -> rasterio.Env:
    """Rasterio environment with portable PROJ/GDAL settings."""
    if not _CONFIGURED:
        configure_geo_runtime()
    return rasterio.Env(
        PROJ_DATA=os.environ.get("PROJ_DATA"),
        PROJ_LIB=os.environ.get("PROJ_LIB"),
        GTIFF_SRS_SOURCE="EPSG",
    )


def _crs_text(crs: Any) -> str:
    if crs is None:
        return ""
    try:
        return pyproj.CRS.from_user_input(crs).to_string()
    except Exception:
        return str(crs)


def is_conus_albers_alias(crs: Any) -> bool:
    """Return True when *crs* is EPSG:2163 or a known alias."""
    if crs is None:
        return False
    text = _crs_text(crs)
    if any(marker in text for marker in _US_NATIONAL_ATLAS_MARKERS):
        return True
    try:
        parsed = pyproj.CRS.from_user_input(crs)
        if parsed.to_epsg() == 2163:
            return True
        if parsed.to_authority() == ("ESRI", "102008"):
            return True
    except Exception:
        return False
    return False


def canonical_crs(crs: Any = CONUS_TARGET_CRS) -> pyproj.CRS:
    """Map CONUS Albers aliases to authoritative EPSG:2163."""
    if crs is None:
        return pyproj.CRS.from_epsg(2163)
    if is_conus_albers_alias(crs):
        return pyproj.CRS.from_epsg(2163)
    return pyproj.CRS.from_user_input(crs)


def crs_equivalent(a: Any, b: Any) -> bool:
    """Compare CRS objects, treating known CONUS aliases as equivalent."""
    if a is None or b is None:
        return a is b
    if is_conus_albers_alias(a) and is_conus_albers_alias(b):
        return True
    try:
        left = canonical_crs(a) if is_conus_albers_alias(a) else pyproj.CRS.from_user_input(a)
        right = canonical_crs(b) if is_conus_albers_alias(b) else pyproj.CRS.from_user_input(b)
        return left.equals(right)
    except Exception:
        return _crs_text(a) == _crs_text(b)


def align_extent_to_features_crs(
    extent_geom: box,
    raster_crs: Any,
    features_crs: Any,
    source_name: str = "raster",
) -> gpd.GeoDataFrame:
    """Build an extent GeoDataFrame in the feature CRS for spatial prefiltering."""
    extent = gpd.GeoDataFrame({"source": [source_name]}, geometry=[extent_geom], crs=raster_crs)
    if features_crs is None:
        return extent
    if crs_equivalent(raster_crs, features_crs):
        return gpd.GeoDataFrame(
            {"source": [source_name]},
            geometry=[extent_geom],
            crs=canonical_crs(features_crs),
        )
    try:
        return extent.to_crs(features_crs)
    except Exception as exc:
        raise RuntimeError(
            "Could not transform raster extent to road-link CRS for prefiltering. "
            f"Raster={source_name}; details: {exc}. "
            "See docs/geo_projection_conus.md."
        ) from exc


def _window_from_bounds(
    dataset: rasterio.io.DatasetReader,
    minx: float,
    miny: float,
    maxx: float,
    maxy: float,
) -> rio_windows.Window:
    """Compute a raster window from geographic bounds using affine inversion."""
    inv = ~dataset.transform
    col_min, row_min = inv * (minx, maxy)
    col_max, row_max = inv * (maxx, miny)
    row_start = int(np.floor(min(row_min, row_max)))
    row_stop = int(np.ceil(max(row_min, row_max)))
    col_start = int(np.floor(min(col_min, col_max)))
    col_stop = int(np.ceil(max(col_min, col_max)))
    window = rio_windows.Window(
        col_start,
        row_start,
        max(col_stop - col_start, 0),
        max(row_stop - row_start, 0),
    )
    full_window = rio_windows.Window(0, 0, dataset.width, dataset.height)
    return window.intersection(full_window)


@dataclass
class SnailGridResult:
    grid: Any
    raster: np.ndarray
    prepared: gpd.GeoDataFrame
    warped: bool
    raster_crs: str
    feature_crs: str
    grid_crs: str


def build_snail_grid(
    dataset: rasterio.io.DatasetReader,
    prepared: gpd.GeoDataFrame,
    target_crs: str = CONUS_TARGET_CRS,
    padding_pixels: int = 2,
) -> SnailGridResult:
    """Build a snail GridDefinition and windowed raster chip with normalized CRS."""
    if prepared.empty:
        empty_grid = intersection.GridDefinition(
            crs=canonical_crs(target_crs).to_string(),
            width=1,
            height=1,
            transform=(1.0, 0.0, 0.0, 0.0, -1.0, 0.0),
        )
        return SnailGridResult(
            grid=empty_grid,
            raster=np.zeros((1, 1), dtype="float32"),
            prepared=prepared,
            warped=False,
            raster_crs=_crs_text(dataset.crs),
            feature_crs=_crs_text(prepared.crs),
            grid_crs=canonical_crs(target_crs).to_string(),
        )

    feature_crs = prepared.crs
    raster_crs = dataset.crs
    grid_target = canonical_crs(target_crs)
    working = prepared
    warped = False

    if feature_crs is not None and not crs_equivalent(feature_crs, grid_target):
        if crs_equivalent(feature_crs, raster_crs):
            working = prepared.set_crs(canonical_crs(feature_crs), allow_override=True)
        else:
            logging.info("Projecting features to %s for snail grid alignment.", grid_target)
            working = prepared.to_crs(grid_target)

    minx, miny, maxx, maxy = working.total_bounds
    pad_x = abs(dataset.transform.a) * padding_pixels
    pad_y = abs(dataset.transform.e) * padding_pixels
    minx, miny, maxx, maxy = (
        minx - pad_x,
        miny - pad_y,
        maxx + pad_x,
        maxy + pad_y,
    )

    window = _window_from_bounds(dataset, minx, miny, maxx, maxy)
    if window.width <= 0 or window.height <= 0:
        raise RuntimeError(
            "Feature bounds did not overlap raster pixels. "
            "Check hazard raster CRS/extent against the network. "
            "See docs/geo_projection_conus.md."
        )
    raster = dataset.read(1, window=window)
    window_transform = dataset.window_transform(window)

    if raster_crs is not None and not crs_equivalent(raster_crs, grid_target):
        dst_transform, dst_width, dst_height = calculate_default_transform(
            raster_crs,
            grid_target,
            int(window.width),
            int(window.height),
            *rio_windows.bounds(window, dataset.transform),
        )
        dst = np.zeros((dst_height, dst_width), dtype=raster.dtype)
        reproject(
            source=raster,
            destination=dst,
            src_transform=window_transform,
            src_crs=raster_crs,
            dst_transform=dst_transform,
            dst_crs=grid_target,
            resampling=Resampling.bilinear,
        )
        raster = dst
        window_transform = dst_transform
        warped = True

    grid = intersection.GridDefinition(
        crs=grid_target.to_string(),
        width=int(raster.shape[1]),
        height=int(raster.shape[0]),
        transform=tuple(window_transform)[:6],
    )

    logging.info(
        "geo_grid raster_crs=%s feature_crs=%s grid_crs=%s warped=%s links=%s",
        _crs_text(raster_crs),
        _crs_text(feature_crs),
        grid_target.to_string(),
        warped,
        len(working),
    )
    return SnailGridResult(
        grid=grid,
        raster=raster,
        prepared=working,
        warped=warped,
        raster_crs=_crs_text(raster_crs),
        feature_crs=_crs_text(feature_crs),
        grid_crs=grid_target.to_string(),
    )


configure_geo_runtime()
