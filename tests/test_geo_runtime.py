"""Tests for portable CONUS geo runtime helpers."""

from __future__ import annotations

import tempfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

from resiflow.geo_runtime import (
    CONUS_TARGET_CRS,
    align_extent_to_features_crs,
    build_snail_grid,
    canonical_crs,
    configure_geo_runtime,
    crs_equivalent,
    get_geo_runtime_status,
    is_conus_albers_alias,
    rasterio_env,
)
from snail import intersection


LOCAL_CS_WKT = (
    'LOCAL_CS["NAD27 / US National Atlas Equal Area",'
    'UNIT["metre",1,AUTHORITY["EPSG","9001"]],'
    'AXIS["Easting",EAST],AXIS["Northing",NORTH]]'
)


def test_canonical_crs_maps_local_cs_alias_to_epsg2163():
    canonical = canonical_crs(LOCAL_CS_WKT)
    assert canonical.to_epsg() == 2163


def test_crs_equivalent_epsg_and_local_cs():
    assert crs_equivalent("EPSG:2163", LOCAL_CS_WKT)
    assert crs_equivalent("ESRI:102008", "EPSG:2163")


def test_is_conus_albers_alias():
    assert is_conus_albers_alias("EPSG:2163")
    assert is_conus_albers_alias(LOCAL_CS_WKT)
    assert not is_conus_albers_alias("EPSG:4326")


def test_configure_geo_runtime_finds_proj_db():
    status = configure_geo_runtime(force=True)
    assert status["proj_data"]
    assert Path(status["proj_data"]).joinpath("proj.db").exists()


def test_get_geo_runtime_status_returns_copy():
    status = get_geo_runtime_status()
    assert "gdal_data" in status
    assert "proj_data" in status


def test_align_extent_to_features_crs_without_reprojection_for_aliases():
    extent_geom = box(0, 0, 1000, 1000)
    aligned = align_extent_to_features_crs(
        extent_geom,
        raster_crs=LOCAL_CS_WKT,
        features_crs="EPSG:2163",
        source_name="test.tif",
    )
    assert aligned.crs.to_epsg() == 2163
    assert len(aligned) == 1


def test_build_snail_grid_smoke(tmp_path: Path):
    transform = from_origin(0, 1000, 100, 100)
    raster_path = tmp_path / "chip.tif"
    data = np.array([[0.0, 1.0], [0.5, 2.0]], dtype="float32")
    with rasterio_env():
        with rasterio.open(
            raster_path,
            "w",
            driver="GTiff",
            height=2,
            width=2,
            count=1,
            dtype="float32",
            crs=CONUS_TARGET_CRS,
            transform=transform,
            nodata=0.0,
        ) as dataset:
            dataset.write(data, 1)

        features = gpd.GeoDataFrame(
            {
                "e_id": ["1", "2"],
                "road_classification": ["primary", "secondary"],
                "trunk_road": [None, None],
                "road_label": [None, None],
                "geometry": [
                    LineString([(50, 950), (150, 950)]),
                    LineString([(50, 850), (150, 850)]),
                ],
            },
            crs=CONUS_TARGET_CRS,
        )
        prepared = intersection.prepare_linestrings(features)
        with rasterio.open(raster_path) as dataset:
            result = build_snail_grid(dataset, prepared)
        splits = intersection.split_linestrings(result.prepared, result.grid)
        assert len(splits) >= 1
        assert result.grid_crs.startswith("EPSG:2163")
        assert result.raster.shape[0] >= 1
        assert result.warped is False
