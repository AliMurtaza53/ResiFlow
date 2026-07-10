"""Hazard framework unit tests."""

from __future__ import annotations

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
import rasterio
from shapely.geometry import LineString

from resiflow.hazards.base import HazardEvent, parse_hazard_config
from resiflow.hazards.flood import FloodHazardSource
from resiflow.hazards.synthetic import (
    bridge_interior,
    gaussian_hotspot,
    resolve_synthetic_generator,
    snow_band,
)

from sioux_falls_fixtures import FLOOD_DEPTH_M, build_sioux_falls_dataset


def test_parse_hazard_config_defaults() -> None:
    cfg = parse_hazard_config({"event_id": "2", "source": "synthetic:bridge_interior"})
    assert cfg["hazard_type"] == "flood"
    assert cfg["event_id"] == "2"
    assert cfg["scenario_param"] == 30
    assert cfg["closure_threshold"] == 30
    assert cfg["source"] == "synthetic:bridge_interior"


def test_flood_hazard_source_resolves_toy_event(tmp_path) -> None:
    config_path, spec, _links = build_sioux_falls_dataset(tmp_path)
    base_path = tmp_path / "toy_data"
    source = FloodHazardSource(base_path)
    assert source.is_toy_mode
    event = source.resolve_event("1")
    assert event.hazard_type == "flood"
    assert event.event_id == "1"
    assert "flood" in event.sources
    assert Path(event.sources["flood"][0]).exists()


def test_bridge_interior_matches_fixture_raster_pattern(tmp_path) -> None:
    _config_path, spec, road_links = build_sioux_falls_dataset(tmp_path)
    synthetic = bridge_interior(
        road_links,
        spec.flooded_edge_ids,
        peak_intensity=FLOOD_DEPTH_M,
        resolution_m=10.0,
        crs=str(road_links.crs),
    )
    assert synthetic.data.max() == pytest.approx(FLOOD_DEPTH_M)
    assert int(np.count_nonzero(synthetic.data)) > 0

    out_path = tmp_path / "synthetic_bridge.tif"
    synthetic.write_geotiff(out_path)
    with rasterio.open(out_path) as dataset:
        assert dataset.crs is not None
        assert float(dataset.read(1).max()) == pytest.approx(FLOOD_DEPTH_M)


def test_synthetic_generators_produce_intensity_only() -> None:
    links = gpd.GeoDataFrame(
        {"e_id": ["e1"]},
        geometry=[LineString([(0, 0), (1000, 0)])],
        crs="EPSG:3857",
    )
    hotspot = gaussian_hotspot(links, center=(500, 0), sigma_m=200, peak_intensity=0.4)
    assert hotspot.intensity_unit == "m_depth"
    assert hotspot.data.max() == pytest.approx(0.4)

    band = snow_band(links, center_y=0, band_width_m=100, peak_intensity_mm=120)
    assert band.intensity_unit == "mm_snow"


def test_resolve_synthetic_generator_registry() -> None:
    assert resolve_synthetic_generator("synthetic:bridge_interior") is bridge_interior
    with pytest.raises(ValueError, match="Unknown synthetic"):
        resolve_synthetic_generator("synthetic:not_a_generator")


def test_snow_fragility_thresholds() -> None:
    from resiflow.fragility.snow_categorical import compute_damage_level_on_snow
    from resiflow.fragility.snow_operational import apply_max_speed_to_links

    assert compute_damage_level_on_snow("primary", 200.0) == "moderate"
    frame = apply_max_speed_to_links(
        pd.DataFrame({"snow_depth_max_mm": [200.0], "free_flow_speeds": [50.0]}),
        snow_key_mm=150,
    )
    assert float(frame["max_speed"].iloc[0]) == 0.0


def test_snow_hazard_source_toy_mode(tmp_path) -> None:
    from resiflow.hazards.snow import SnowHazardSource

    _config_path, _spec, _links = build_sioux_falls_dataset(tmp_path, hazard="snow")
    source = SnowHazardSource(tmp_path / "toy_data")
    assert source.is_toy_mode
    event = source.resolve_event("1")
    assert event.hazard_type == "snow"
    assert event.intensity_unit == "mm_snow"
