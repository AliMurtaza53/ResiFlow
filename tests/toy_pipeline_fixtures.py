"""Build temporary toy datasets for end-to-end pipeline script tests."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

from resiflow.geo_runtime import CONUS_TARGET_CRS

REPO_ROOT = Path(__file__).resolve().parents[1]
PARAMETERS_SRC = REPO_ROOT / "parameters"
TARGET_CRS = CONUS_TARGET_CRS
FLOOD_DEPTH_M = 0.50  # 50 cm, above default depth_key=30
PASSENGER_OD_FILENAME = "lodes_passenger_assignment_od_jt00_2022.parquet"


@dataclass(frozen=True)
class ToyNetworkSpec:
    name: str
    flooded_edge_id: str
    baseline_path_edges: tuple[str, ...]
    baseline_edge_flows: dict[str, float]
    reroute_gain_edge: str
    expected_disrupted_flow_freight: float
    expected_disrupted_flow_passenger: float
    expected_rerouting_cost_freight: float
    expected_rerouting_cost_passenger: float
    expected_reroute_flow_freight: float
    expected_reroute_flow_passenger: float
    origin_node: str
    destination_node: str
    freight_flow: float
    passenger_flow: float
    lanes: int = 1
    flow_cap_plph: int = 1
    hazard_interior_fraction: tuple[float, float] | None = None
    hazard_resolution_m: float = 200.0


def _edge_row(
    e_id: str,
    from_id: str,
    to_id: str,
    coords: list[tuple[float, float]],
    *,
    speed_mph: float,
    road_classification: str = "local",
    lanes: int = 1,
) -> dict:
    return {
        "e_id": e_id,
        "from_id": from_id,
        "to_id": to_id,
        "road_classification": road_classification,
        "trunk_road": False,
        "road_label": "road",
        "lanes": lanes,
        "urban": 0,
        "form_of_way": "Single Carriageway",
        "average_toll_cost": 0.0,
        "free_flow_speeds": speed_mph,
        "geometry": LineString(coords),
    }


def three_parallel_edges() -> list[dict]:
  return [
      _edge_row("e_fast", "n1", "n2", [(0, 200), (10000, 200)], speed_mph=70.0),
      _edge_row("e_mid", "n1", "n2", [(0, 0), (10000, 0)], speed_mph=50.0),
      _edge_row("e_slow", "n1", "n2", [(0, -200), (10000, -200)], speed_mph=30.0),
  ]


def braess_edges() -> list[dict]:
    return [
        _edge_row("e_12", "n1", "n2", [(0, 5000), (5000, 10000)], speed_mph=45.0),
        _edge_row("e_13", "n1", "n3", [(0, 5000), (5000, 0)], speed_mph=15.0),
        _edge_row("e_23", "n2", "n3", [(5000, 10000), (5000, 0)], speed_mph=80.0),
        _edge_row("e_24", "n2", "n4", [(5000, 10000), (10000, 5000)], speed_mph=5.0),
        _edge_row("e_34", "n3", "n4", [(5000, 0), (10000, 5000)], speed_mph=45.0),
    ]


def network_edges(name: str) -> list[dict]:
    if name == "three_parallel":
        return three_parallel_edges()
    if name == "braess":
        return braess_edges()
    raise ValueError(f"Unknown toy network: {name}")


def network_spec(name: str) -> ToyNetworkSpec:
    if name == "three_parallel":
        return ToyNetworkSpec(
            name=name,
            flooded_edge_id="e_fast",
            baseline_path_edges=("e_fast", "e_mid", "e_slow"),
            baseline_edge_flows={"e_fast": 24.0, "e_mid": 24.0, "e_slow": 24.0},
            reroute_gain_edge="e_mid",
            expected_disrupted_flow_freight=100.0,
            expected_disrupted_flow_passenger=30.0,
            expected_rerouting_cost_freight=-95.27435151515712,
            expected_rerouting_cost_passenger=25.071499098705655,
            expected_reroute_flow_freight=24.0,
            expected_reroute_flow_passenger=24.0,
            origin_node="n1",
            destination_node="n2",
            freight_flow=100.0,
            passenger_flow=30.0,
        )
    if name == "braess":
        return ToyNetworkSpec(
            name=name,
            flooded_edge_id="e_23",
            baseline_path_edges=("e_12", "e_23", "e_34"),
            baseline_edge_flows={"e_12": 24.0, "e_23": 24.0, "e_34": 24.0, "e_13": 0.0},
            reroute_gain_edge="e_13",
            expected_disrupted_flow_freight=12.0,
            expected_disrupted_flow_passenger=13.0,
            expected_rerouting_cost_freight=5.160587707273884,
            expected_rerouting_cost_passenger=5.5906366828800245,
            expected_reroute_flow_freight=12.0,
            expected_reroute_flow_passenger=13.0,
            origin_node="n1",
            destination_node="n4",
            freight_flow=12.0,
            passenger_flow=13.0,
            hazard_interior_fraction=(0.35, 0.65),
            hazard_resolution_m=50.0,
        )
    raise ValueError(f"Unknown toy network: {name}")


def write_road_links(toy_data_dir: Path, edges: list[dict]) -> gpd.GeoDataFrame:
    gdf = gpd.GeoDataFrame(edges, crs=TARGET_CRS)
    out = toy_data_dir / "inputs" / "networks" / "faf5" / "faf5_road_links.gpq"
    out.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_parquet(out)
    return gdf


def write_od_matrix(toy_data_dir: Path, origin: str, destination: str, flow: float = 100.0) -> None:
    od = pd.DataFrame(
        [{"origin_node": origin, "destination_node": destination, "Car21": flow}]
    )
    out = toy_data_dir / "inputs" / "census_datasets" / "faf5_od_matrix.pq"
    out.parent.mkdir(parents=True, exist_ok=True)
    od.to_parquet(out, index=False)


def passenger_od_path(toy_data_dir: Path) -> Path:
    """Mirror production layout for Script 1 / Script 4 passenger OD lookup."""
    return toy_data_dir / "lodes_data" / "processed" / PASSENGER_OD_FILENAME


def write_passenger_od_matrix(
    toy_data_dir: Path,
    origin: str,
    destination: str,
    flow: float,
) -> Path:
    od = pd.DataFrame(
        [{"origin_node": origin, "destination_node": destination, "Car21": flow}]
    )
    out = passenger_od_path(toy_data_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    od.to_parquet(out, index=False)
    return out


def copy_parameters(toy_data_dir: Path, *, flow_cap_plph: int = 1) -> None:
    dest = toy_data_dir / "inputs" / "parameters"
    dest.mkdir(parents=True, exist_ok=True)
    for name in (
        "assignment_profiles.json",
        "network_mapping.faf5.json",
        "network_mapping.osm.json",
        "network_mapping.tntp.json",
        "unified_parameters.json",
    ):
        shutil.copy2(PARAMETERS_SRC / name, dest / name)
    cap_value = int(flow_cap_plph)
    tier_caps = {
        "freeway": cap_value,
        "arterial": cap_value,
        "collector": cap_value,
        "local_access": cap_value,
    }
    profiles_path = dest / "assignment_profiles.json"
    profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    profiles["flow_cap_plph"] = tier_caps
    profiles_path.write_text(json.dumps(profiles, indent=2), encoding="utf-8")


def write_recovery_table(toy_data_dir: Path) -> None:
    rows = [
        {
            "scenario": 1,
            "event_day": 1,
            "bridge_minor": 0.5,
            "bridge_moderate": 0.4,
            "bridge_extensive": 0.3,
            "bridge_severe": 0.2,
            "road_minor": 0.6,
            "road_moderate": 0.5,
            "road_extensive": 0.4,
            "road_severe": 0.3,
        }
    ]
    out = toy_data_dir / "tables" / "recovery design_updated.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(out, index=False)


def write_damage_workbooks(toy_data_dir: Path) -> None:
    ratio = pd.DataFrame(
        {
            "intensity": [0.0, 0.25, 0.5, 1.0],
            "Interstate": [0.0, 0.1, 0.3, 0.6],
            "US Route": [0.0, 0.1, 0.25, 0.5],
            "State Route": [0.0, 0.08, 0.2, 0.45],
            "Local": [0.0, 0.05, 0.15, 0.35],
        }
    )
    roads = pd.DataFrame(
        {
            "label": ["m_ge8_urb", "m_lt8_urb", "absingle_urb", "roadsingle_urb"],
            "min": [1.0, 1.0, 1.0, 1.0],
            "max": [2.0, 2.0, 2.0, 2.0],
            "mean": [1.5, 1.5, 1.5, 1.5],
        }
    )
    bridges = pd.DataFrame({"label": ["bridge"], "min": [10.0], "max": [20.0], "mean": [15.0]})

    curves_dir = toy_data_dir / "damage_curves"
    costs_dir = toy_data_dir / "asset_costs"
    curves_dir.mkdir(parents=True, exist_ok=True)
    costs_dir.mkdir(parents=True, exist_ok=True)

    ratio.to_excel(curves_dir / "damage_ratio_road_flood.xlsx", index=False)
    with pd.ExcelWriter(costs_dir / "damage_cost_road_flood.xlsx") as writer:
        roads.to_excel(writer, sheet_name="roads", index=False)
        bridges.to_excel(writer, sheet_name="bridges-surface", index=False)
        bridges.to_excel(writer, sheet_name="bridges-river", index=False)


def write_study_area(toy_data_dir: Path, road_links: gpd.GeoDataFrame) -> None:
    minx, miny, maxx, maxy = road_links.total_bounds
    pad = 2000.0
    geom = box(minx - pad, miny - pad, maxx + pad, maxy + pad)
    gdf = gpd.GeoDataFrame({"name": ["toy"]}, geometry=[geom], crs=TARGET_CRS)
    out = toy_data_dir / "study_area" / "fairfax_study_area.geojson"
    out.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out, driver="GeoJSON")


def write_hazard_raster(
    toy_data_dir: Path,
    road_links: gpd.GeoDataFrame,
    flooded_edge_id: str,
    *,
    resolution_m: float = 200.0,
    interior_fraction: tuple[float, float] | None = None,
) -> None:
    flooded = road_links.loc[road_links["e_id"] == flooded_edge_id]
    if flooded.empty:
        raise ValueError(f"Flooded edge not found: {flooded_edge_id}")

    minx, miny, maxx, maxy = road_links.total_bounds
    pad = 1000.0
    minx -= pad
    miny -= pad
    maxx += pad
    maxy += pad
    width = int(np.ceil((maxx - minx) / resolution_m))
    height = int(np.ceil((maxy - miny) / resolution_m))
    transform = from_origin(minx, maxy, resolution_m, resolution_m)

    if interior_fraction is not None:
        start_frac, end_frac = interior_fraction
        hazard_geoms = []
        for geom in flooded.geometry:
            start = geom.interpolate(start_frac, normalized=True)
            end = geom.interpolate(end_frac, normalized=True)
            hazard_geoms.append(LineString([(start.x, start.y), (end.x, end.y)]))
        shapes = [(geom, FLOOD_DEPTH_M) for geom in hazard_geoms]
    else:
        shapes = [(geom.buffer(resolution_m), FLOOD_DEPTH_M) for geom in flooded.geometry]
    data = rasterize(shapes, out_shape=(height, width), transform=transform, fill=0.0)

    hazard_dir = toy_data_dir / "inputs" / "test_141node_50m"
    hazard_dir.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": TARGET_CRS,
        "transform": transform,
        "nodata": -9999.0,
    }
    for variant in ("base", "low", "high"):
        out = hazard_dir / f"va_hazard_class50_141node_{variant}.tif"
        with rasterio.open(out, "w", **profile) as dst:
            dst.write(data.astype("float32"), 1)


def write_toy_config(tmp_path: Path, toy_data_dir: Path) -> Path:
    config = {
        "paths": {
            "soge_clusters": str(toy_data_dir),
            "base_path": str(toy_data_dir),
            "output_path": str(tmp_path / "results"),
        }
    }
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
    return config_path


def build_toy_dataset(tmp_path: Path, network_name: str) -> tuple[Path, ToyNetworkSpec, gpd.GeoDataFrame]:
    spec = network_spec(network_name)
    toy_data_dir = tmp_path / "toy_data"
    toy_data_dir.mkdir(parents=True, exist_ok=True)

    edges = network_edges(network_name)
    for edge in edges:
        edge["lanes"] = spec.lanes
    road_links = write_road_links(toy_data_dir, edges)
    write_od_matrix(
        toy_data_dir,
        origin=spec.origin_node,
        destination=spec.destination_node,
        flow=spec.freight_flow,
    )
    write_passenger_od_matrix(
        toy_data_dir,
        origin=spec.origin_node,
        destination=spec.destination_node,
        flow=spec.passenger_flow,
    )

    copy_parameters(toy_data_dir, flow_cap_plph=spec.flow_cap_plph)
    write_recovery_table(toy_data_dir)
    write_damage_workbooks(toy_data_dir)
    write_study_area(toy_data_dir, road_links)
    write_hazard_raster(
        toy_data_dir,
        road_links,
        spec.flooded_edge_id,
        resolution_m=spec.hazard_resolution_m,
        interior_fraction=spec.hazard_interior_fraction,
    )
    config_path = write_toy_config(tmp_path, toy_data_dir)
    return config_path, spec, road_links


def pipeline_env(
    tmp_path: Path,
    config_path: Path,
    *,
    network_name: str,
) -> dict[str, str]:
    variant = f"toy_{network_name}"
    toy_data_dir = tmp_path / "toy_data"
    env = os.environ.copy()
    env["NIRD_CONFIG_PATH"] = str(config_path)
    env["NIRD_RESULTS_VARIANT"] = variant
    env["NIRD_BASE_SCENARIO_OUT_DIR"] = str(
        tmp_path / "results" / "base_scenario" / variant
    )
    env["NIRD_BASELINE_DB_PATH"] = str(toy_data_dir / "dbs" / "baseline.duckdb")
    env["NIRD_RECOVERY_DB_PATH"] = str(toy_data_dir / "dbs" / "recovery_30_1.duckdb")
    env["NIRD_DIRECT_DUCKDB_OUTPUTS"] = "1"
    env["NIRD_PATH_REALIZATION_STRATEGY"] = "streaming_arrays"
    env["NIRD_BASELINE_PATH_OUTPUT_MODE"] = "full_odpfc"
    env["NIRD_SAMPLE_OD_N"] = "0"
    env["NIRD_PASSENGER_OD_PATH"] = str(passenger_od_path(toy_data_dir))
    env["NIRD_ENABLE_PASSENGER_REROUTING"] = "1"
    env["NIRD_TOY_FLOOD_TYPES"] = "flood"
    env.pop("NIRD_DISABLE_PASSENGER_OD", None)
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + str(REPO_ROOT)
    return env


def run_script(script_name: str, args: Iterable[str], env: dict[str, str]) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(REPO_ROOT / "scripts" / script_name), *map(str, args)]
    return subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def run_pipeline_scripts(env: dict[str, str]) -> None:
    run_script("1_network_flow_model_revision.py", ["1", "1"], env)
    run_script("2_intersection_analysis.py", ["30", "1"], env)
    run_script("3_damage_analysis.py", [], env)
    run_script("4_rerouting_and_recovery_scenario_loop.py", ["30", "1", "1", "1"], env)


def results_variant(env: dict[str, str]) -> str:
    return env["NIRD_RESULTS_VARIANT"]


def base_scenario_dir(tmp_path: Path, env: dict[str, str]) -> Path:
    return tmp_path / "results" / "base_scenario" / results_variant(env)


def disruption_dir(tmp_path: Path, env: dict[str, str], depth_key: int = 30) -> Path:
    return tmp_path / "results" / "disruption_analysis" / results_variant(env) / str(depth_key)


def damage_dir(tmp_path: Path, env: dict[str, str], scenario_param: int = 30) -> Path:
    return (
        tmp_path
        / "results"
        / "damage_analysis"
        / results_variant(env)
        / str(scenario_param)
    )


def reroute_dir(tmp_path: Path, env: dict[str, str], depth_key: int = 30, event_key: int = 1) -> Path:
    return (
        tmp_path
        / "results"
        / "rerouting_analysis"
        / results_variant(env)
        / str(depth_key)
        / str(event_key)
    )
