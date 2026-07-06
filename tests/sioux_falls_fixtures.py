"""Build a Sioux Falls FAF5-compatible fixture for pipeline tests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely.geometry import LineString, Point, box

from toy_pipeline_fixtures import (
    FLOOD_DEPTH_M,
    PASSENGER_OD_FILENAME,
    copy_parameters,
    pipeline_env,
    run_pipeline_scripts,
    write_recovery_table,
    write_toy_config,
)

# TNTP node X/Y are geographic coordinates (bstabler SiouxFallsCoordinates.geojson).
SOURCE_CRS = "EPSG:4326"
# Rasterio persists CONUS Albers as EPSG:9311; align link + hazard CRS to avoid
# Script 2 reprojection shifting geometries off the 10 m flood grid.
OUTPUT_CRS = "EPSG:9311"
DATA_DIR = Path(__file__).resolve().parent / "data" / "sioux_falls_tntp"
REFERENCE_GEOJSON = DATA_DIR / "SiouxFallsCoordinates.geojson"
DEMAND_SCALE = 0.3
FREIGHT_SHARE_OF_PASSENGER = 0.09
FLOODED_PHYSICAL_PAIR = ("10", "15")
BRIDGE_PHYSICAL_PAIRS = {
    ("10", "15"),
    ("15", "22"),
    ("10", "16"),
    ("8", "16"),
    ("11", "14"),
}


@dataclass(frozen=True)
class SiouxFallsSpec:
    origin_node: str
    destination_node: str
    flooded_edge_ids: tuple[str, ...]
    bridge_edge_ids: tuple[str, ...]
    reroute_gain_edge_ids: tuple[str, ...]
    link_count: int
    scaled_passenger_demand: float
    scaled_freight_demand: float


def _node_id(raw: str | int) -> str:
    return f"sf_{raw}"


def _physical_pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((str(a), str(b))))


def read_tntp_nodes(path: Path = DATA_DIR / "SiouxFalls_node.tntp") -> pd.DataFrame:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.lower().startswith("node"):
            continue
        parts = stripped.replace(";", "").split()
        if len(parts) >= 3:
            rows.append({"node": parts[0], "x": float(parts[1]), "y": float(parts[2])})
    if not rows:
        raise ValueError(f"No nodes parsed from {path}")
    return pd.DataFrame(rows)


def read_reference_nodes(path: Path = REFERENCE_GEOJSON) -> gpd.GeoDataFrame:
    """Load the canonical bstabler Sioux Falls node coordinates (EPSG:4326)."""
    return gpd.read_file(path)


def read_tntp_links(path: Path = DATA_DIR / "SiouxFalls_net.tntp") -> pd.DataFrame:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("<") or stripped.startswith("~"):
            continue
        parts = stripped.replace(";", "").split()
        if len(parts) >= 10:
            rows.append(
                {
                    "init_node": parts[0],
                    "term_node": parts[1],
                    "capacity": float(parts[2]),
                    "length": float(parts[3]),
                    "free_flow_time": float(parts[4]),
                    "toll": float(parts[8]),
                    "link_type": parts[9],
                }
            )
    if not rows:
        raise ValueError(f"No links parsed from {path}")
    return pd.DataFrame(rows)


def read_tntp_trips(path: Path = DATA_DIR / "SiouxFalls_trips.tntp") -> pd.DataFrame:
    rows = []
    origin: str | None = None
    pair_re = re.compile(r"(\d+)\s*:\s*([0-9.]+)")
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("<"):
            continue
        if stripped.lower().startswith("origin"):
            origin = stripped.split()[1]
            continue
        if origin is None:
            continue
        for destination, flow_raw in pair_re.findall(stripped):
            flow = float(flow_raw)
            if flow > 0.0 and destination != origin:
                rows.append(
                    {
                        "origin_node": _node_id(origin),
                        "destination_node": _node_id(destination),
                        "Car21": flow,
                    }
                )
    if not rows:
        raise ValueError(f"No OD rows parsed from {path}")
    return pd.DataFrame(rows)


def build_node_geometries(nodes: pd.DataFrame) -> dict[str, Point]:
    """Use TNTP X/Y directly as WGS84 lon/lat.

    The vendored ``SiouxFalls_node.tntp`` X/Y columns are the geographic
    coordinates published in the bstabler ``SiouxFallsCoordinates.geojson``
    (EPSG:4326). Returning them unscaled keeps the testbed's spatial
    representation aligned with the canonical Sioux Falls layout. Callers
    reproject to the pipeline CRS (``OUTPUT_CRS``) before writing outputs.
    """
    coords = nodes[["x", "y"]].to_numpy(dtype=float)
    span = float(np.ptp(coords, axis=0).max())
    if span <= 0.0:
        raise ValueError("Node coordinates have zero extent")

    geometries: dict[str, Point] = {}
    for row in nodes.itertuples(index=False):
        geometries[str(row.node)] = Point(float(row.x), float(row.y))
    return geometries


def _road_classification(capacity: float) -> str:
    # Use non-major classes so Script 2 does not subtract the 200 cm embankment
    # from the 50 cm toy hazard (primary/secondary would zero out flood depth).
    if capacity >= 15_000:
        return "tertiary"
    return "local"


def _lanes(capacity: float) -> int:
    if capacity >= 20_000:
        return 3
    if capacity >= 10_000:
        return 2
    return 1


def _flow_cap_plph_from_tntp(capacity_vph: float, lanes: int) -> float:
    """Map TNTP link capacity (veh/hr) to NIRD per-lane hourly design capacity."""
    lane_count = max(int(lanes), 1)
    return float(capacity_vph) / lane_count


def write_sioux_falls_damage_workbooks(toy_data_dir: Path) -> None:
    """Scaled damage curves so direct damage stays in plausible testbed ranges."""
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
            "min": [0.001, 0.001, 0.001, 0.001],
            "max": [0.002, 0.002, 0.002, 0.002],
            "mean": [0.0015, 0.0015, 0.0015, 0.0015],
        }
    )
    bridges = pd.DataFrame(
        {"label": ["bridge"], "min": [1e-8], "max": [2e-8], "mean": [1.5e-8]}
    )

    curves_dir = toy_data_dir / "damage_curves"
    costs_dir = toy_data_dir / "asset_costs"
    curves_dir.mkdir(parents=True, exist_ok=True)
    costs_dir.mkdir(parents=True, exist_ok=True)

    ratio.to_excel(curves_dir / "damage_ratio_road_flood.xlsx", index=False)
    with pd.ExcelWriter(costs_dir / "damage_cost_road_flood.xlsx") as writer:
        roads.to_excel(writer, sheet_name="roads", index=False)
        bridges.to_excel(writer, sheet_name="bridges-surface", index=False)
        bridges.to_excel(writer, sheet_name="bridges-river", index=False)


def write_road_links(toy_data_dir: Path) -> tuple[gpd.GeoDataFrame, SiouxFallsSpec]:
    nodes = read_tntp_nodes()
    links = read_tntp_links()
    node_geoms = build_node_geometries(nodes)

    bridge_pairs = {_physical_pair(*pair) for pair in BRIDGE_PHYSICAL_PAIRS}
    flooded_pair = _physical_pair(*FLOODED_PHYSICAL_PAIR)
    rows = []
    flooded_edge_ids: list[str] = []
    bridge_edge_ids: list[str] = []
    reroute_gain_edge_ids: list[str] = []

    for idx, row in enumerate(links.itertuples(index=False)):
        start = str(row.init_node)
        end = str(row.term_node)
        pair = _physical_pair(start, end)
        e_id = f"sf_{start}_{end}_{idx}"
        tntp_capacity_vph = float(row.capacity)
        lane_count = _lanes(tntp_capacity_vph)
        speed_mph = (
            (float(row.length) / (float(row.free_flow_time) / 60.0))
            if float(row.free_flow_time) > 0.0
            else 35.0
        )
        is_bridge = pair in bridge_pairs
        if pair == flooded_pair:
            flooded_edge_ids.append(e_id)
        if is_bridge:
            bridge_edge_ids.append(e_id)
        if pair == _physical_pair("11", "14"):
            reroute_gain_edge_ids.append(e_id)
        rows.append(
            {
                "e_id": e_id,
                "from_id": _node_id(start),
                "to_id": _node_id(end),
                "road_classification": _road_classification(tntp_capacity_vph),
                "trunk_road": False,
                "road_label": "bridge" if is_bridge else "road",
                "facility_type": "Bridge" if is_bridge else "Highway",
                "lanes": lane_count,
                "tntp_capacity_vph": tntp_capacity_vph,
                "flow_cap_plph": _flow_cap_plph_from_tntp(tntp_capacity_vph, lane_count),
                "urban": 1,
                "form_of_way": "Single Carriageway",
                "average_toll_cost": float(row.toll),
                "free_flow_speeds": min(speed_mph, 45.0),
                "averageWidth": 11.0 if is_bridge else 3.65 * lane_count,
                "geometry": LineString([node_geoms[start], node_geoms[end]]),
            }
        )

    # Nodes are WGS84 lon/lat; build in 4326 then reproject to the pipeline CRS.
    road_links = gpd.GeoDataFrame(rows, crs=SOURCE_CRS).to_crs(OUTPUT_CRS)
    out = toy_data_dir / "inputs" / "networks" / "faf5" / "faf5_road_links.gpq"
    out.parent.mkdir(parents=True, exist_ok=True)
    road_links.to_parquet(out)

    passenger = read_tntp_trips()
    scaled_passenger = float(passenger["Car21"].sum()) * DEMAND_SCALE
    scaled_freight = scaled_passenger * FREIGHT_SHARE_OF_PASSENGER

    spec = SiouxFallsSpec(
        origin_node=_node_id(10),
        destination_node=_node_id(24),
        flooded_edge_ids=tuple(flooded_edge_ids),
        bridge_edge_ids=tuple(bridge_edge_ids),
        reroute_gain_edge_ids=tuple(reroute_gain_edge_ids),
        link_count=len(road_links),
        scaled_passenger_demand=scaled_passenger,
        scaled_freight_demand=scaled_freight,
    )
    return road_links, spec


def write_od_matrices(toy_data_dir: Path) -> None:
    passenger = read_tntp_trips()
    passenger["Car21"] = passenger["Car21"] * DEMAND_SCALE
    passenger_out = (
        toy_data_dir
        / "lodes_data"
        / "processed"
        / PASSENGER_OD_FILENAME
    )
    passenger_out.parent.mkdir(parents=True, exist_ok=True)
    passenger.to_parquet(passenger_out, index=False)

    freight = passenger.copy()
    freight["Car21"] = freight["Car21"] * FREIGHT_SHARE_OF_PASSENGER
    freight_out = toy_data_dir / "inputs" / "census_datasets" / "faf5_od_matrix.pq"
    freight_out.parent.mkdir(parents=True, exist_ok=True)
    freight.to_parquet(freight_out, index=False)


def write_study_area(toy_data_dir: Path, road_links: gpd.GeoDataFrame) -> None:
    minx, miny, maxx, maxy = road_links.total_bounds
    pad = 2_000.0
    gdf = gpd.GeoDataFrame(
        {"name": ["sioux_falls"]},
        geometry=[box(minx - pad, miny - pad, maxx + pad, maxy + pad)],
        crs=road_links.crs,
    )
    out = toy_data_dir / "study_area" / "fairfax_study_area.geojson"
    out.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(out, driver="GeoJSON")


def write_hazard_raster(
    toy_data_dir: Path,
    road_links: gpd.GeoDataFrame,
    flooded_edge_ids: tuple[str, ...],
    *,
    resolution_m: float = 10.0,
    interior_fraction: tuple[float, float] = (0.35, 0.65),
) -> None:
    """Rasterize a full-network extent grid; only the bridge interior gets depth > 0."""
    flooded = road_links.loc[road_links["e_id"].isin(flooded_edge_ids)]
    if flooded.empty:
        raise ValueError("No flooded Sioux Falls bridge edges found")

    minx, miny, maxx, maxy = road_links.total_bounds
    pad = 500.0
    minx -= pad
    miny -= pad
    maxx += pad
    maxy += pad
    width = int(np.ceil((maxx - minx) / resolution_m))
    height = int(np.ceil((maxy - miny) / resolution_m))
    transform = from_origin(minx, maxy, resolution_m, resolution_m)

    start_frac, end_frac = interior_fraction
    shapes = []
    hazard_buffer_m = resolution_m * 0.5
    for geom in flooded.geometry:
        start = geom.interpolate(start_frac, normalized=True)
        end = geom.interpolate(end_frac, normalized=True)
        interior = LineString([(start.x, start.y), (end.x, end.y)])
        shapes.append((interior.buffer(hazard_buffer_m), FLOOD_DEPTH_M))

    data = rasterize(
        shapes,
        out_shape=(height, width),
        transform=transform,
        fill=0.0,
        all_touched=True,
    )
    hazard_dir = toy_data_dir / "inputs" / "test_141node_50m"
    hazard_dir.mkdir(parents=True, exist_ok=True)
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": OUTPUT_CRS,
        "transform": transform,
        "nodata": -9999.0,
    }
    for variant in ("base", "low", "high"):
        with rasterio.open(
            hazard_dir / f"va_hazard_class50_141node_{variant}.tif",
            "w",
            **profile,
        ) as dst:
            dst.write(data.astype("float32"), 1)


def build_sioux_falls_dataset(tmp_path: Path) -> tuple[Path, SiouxFallsSpec, gpd.GeoDataFrame]:
    toy_data_dir = tmp_path / "toy_data"
    toy_data_dir.mkdir(parents=True, exist_ok=True)

    road_links, spec = write_road_links(toy_data_dir)
    write_od_matrices(toy_data_dir)
    copy_parameters(toy_data_dir)
    write_recovery_table(toy_data_dir)
    write_sioux_falls_damage_workbooks(toy_data_dir)
    write_study_area(toy_data_dir, road_links)
    write_hazard_raster(
        toy_data_dir,
        road_links,
        spec.flooded_edge_ids,
        resolution_m=10.0,
    )
    config_path = write_toy_config(tmp_path, toy_data_dir)
    return config_path, spec, road_links


def sioux_falls_env(tmp_path: Path, config_path: Path) -> dict[str, str]:
    env = pipeline_env(tmp_path, config_path, network_name="sioux_falls")
    env["NIRD_TESTBED"] = "1"
    return env
