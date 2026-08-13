"""Build a Sioux Falls FAF5-compatible fixture for pipeline tests."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.features import rasterize
from rasterio.transform import from_origin
from shapely.geometry import LineString, box

from resiflow.demand.tntp import load_tntp_trips, split_freight_passenger
from resiflow.networks.tntp import (
    build_node_geometries,
    read_tntp_links,
    read_tntp_nodes,
    read_tntp_trips,
)
from resiflow.testbeds import load_testbed

from toy_pipeline_fixtures import (
    FLOOD_DEPTH_M,
    PASSENGER_OD_FILENAME,
    copy_parameters,
    pipeline_env,
    run_pipeline_scripts,
    run_script,
    write_recovery_table,
    write_toy_config,
)

SNOW_DEPTH_MM = 200.0
SNOW_SCENARIO_KEY_MM = 150

TESTBED = load_testbed("sioux_falls")
SOURCE_CRS = TESTBED.source_crs
OUTPUT_CRS = TESTBED.output_crs
DATA_DIR = TESTBED.data_dir
REFERENCE_GEOJSON = DATA_DIR / (TESTBED.reference_geojson or "SiouxFallsCoordinates.geojson")
DEMAND_SCALE = TESTBED.demand_scale
FREIGHT_SHARE_OF_PASSENGER = TESTBED.freight_share_of_passenger
FLOODED_PHYSICAL_PAIR = TESTBED.flooded_physical_pair or ("10", "15")
BRIDGE_PHYSICAL_PAIRS = {tuple(pair) for pair in TESTBED.bridge_physical_pairs}


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
    # Only populated for the heterogeneous variant: per-edge graded flood depth (m).
    flood_depth_by_edge: dict[str, float] | None = None


def _node_id(raw: str | int) -> str:
    return TESTBED.node_id_formatter()(raw)


def _physical_pair(a: str, b: str) -> tuple[str, str]:
    return tuple(sorted((str(a), str(b))))


def read_reference_nodes(path: Path = REFERENCE_GEOJSON) -> gpd.GeoDataFrame:
    """Load the canonical bstabler Sioux Falls node coordinates (EPSG:4326)."""
    return gpd.read_file(path)


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


# --- Heterogeneous variant knobs (opt-in; the default fixture is unchanged) ----
# Deterministic per-link cycles that break the near-uniform link attributes that
# collapse the toy Morris sensitivity onto a few points. Lanes and width are
# decoupled (width is not a strict multiple of lanes) so they register as
# separate factors rather than one collinear cluster.
_HETERO_LANES_CYCLE = (1, 2, 3, 4, 2, 3, 1, 4)
_HETERO_WIDTH_CYCLE = (3.65, 5.5, 7.3, 9.0, 11.0, 14.6)
# Non-major classes only (majors are stripped to zero depth by the embankment
# rule at these depths). Mixed Script-5 codes for input variety; note class does
# not move the toy damage cost, so it stays a low-effect factor by design.
_HETERO_CLASS_CYCLE = ("tertiary", "A Road", "B Road", "tertiary", "local")
# Number of leading (mostly non-bridge) links added to the flooded corridor, on
# top of the bridge pairs and the canonical flooded pair.
_HETERO_CORRIDOR_LINKS = 16
_HETERO_DEPTH_MIN_M = 0.35
_HETERO_DEPTH_MAX_M = 1.0


def _hetero_link_attrs(idx: int, is_bridge: bool) -> tuple[int, float, str]:
    """Return (lanes, averageWidth, road_classification) for the heterogeneous build."""
    lanes = _HETERO_LANES_CYCLE[idx % len(_HETERO_LANES_CYCLE)]
    if is_bridge:
        return lanes, 11.0, "tertiary"
    width = _HETERO_WIDTH_CYCLE[idx % len(_HETERO_WIDTH_CYCLE)]
    rc = _HETERO_CLASS_CYCLE[idx % len(_HETERO_CLASS_CYCLE)]
    return lanes, width, rc


def _graded_depths(edge_ids: list[str]) -> dict[str, float]:
    """Assign a monotone spread of flood depths (m) across the corridor edges."""
    n = len(edge_ids)
    if n == 0:
        return {}
    if n == 1:
        return {edge_ids[0]: _HETERO_DEPTH_MAX_M}
    span = _HETERO_DEPTH_MAX_M - _HETERO_DEPTH_MIN_M
    return {
        e_id: round(_HETERO_DEPTH_MIN_M + span * (rank / (n - 1)), 3)
        for rank, e_id in enumerate(sorted(edge_ids))
    }


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
    # ``m_lt8_urb`` already exists; ``asingle_urb`` / ``bsingle_urb`` are the keys
    # Script 3 actually generates for major- and minor-class single carriageways
    # (see 3_damage_analysis.py compute_damage_values). Without them a flooded
    # *road* (as opposed to a bridge) falls through to a zero default unit cost,
    # which is fine for the bridge-only default fixture but zeroes out the
    # heterogeneous corridor's road damage. Give the three tiers distinct unit
    # costs so road class/structure actually move the direct damage target.
    roads = pd.DataFrame(
        {
            "label": [
                "m_ge8_urb",
                "m_lt8_urb",
                "absingle_urb",
                "roadsingle_urb",
                "asingle_urb",
                "bsingle_urb",
            ],
            "min": [0.001, 0.001, 0.001, 0.001, 0.006, 0.003],
            "max": [0.002, 0.002, 0.002, 0.002, 0.012, 0.006],
            "mean": [0.0015, 0.0015, 0.0015, 0.0015, 0.009, 0.0045],
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


def write_road_links(
    toy_data_dir: Path, *, heterogeneous: bool = False
) -> tuple[gpd.GeoDataFrame, SiouxFallsSpec]:
    nodes = read_tntp_nodes(TESTBED.node_path())
    links = read_tntp_links(TESTBED.net_path())
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
        is_bridge = pair in bridge_pairs
        speed_mph = (
            (float(row.length) / (float(row.free_flow_time) / 60.0))
            if float(row.free_flow_time) > 0.0
            else 35.0
        )
        if heterogeneous:
            lane_count, avg_width, road_class = _hetero_link_attrs(idx, is_bridge)
        else:
            lane_count = _lanes(tntp_capacity_vph)
            avg_width = 11.0 if is_bridge else 3.65 * lane_count
            road_class = _road_classification(tntp_capacity_vph)

        # Flooded set: default = the canonical pair only; heterogeneous = a graded
        # corridor of leading links + all bridges + the canonical pair (roads and
        # bridges of varied lanes/width so the direct-damage target is not driven
        # by a single homogeneous pair).
        if heterogeneous:
            if idx < _HETERO_CORRIDOR_LINKS or is_bridge or pair == flooded_pair:
                flooded_edge_ids.append(e_id)
        elif pair == flooded_pair:
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
                "road_classification": road_class,
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
                "averageWidth": avg_width,
                "geometry": LineString([node_geoms[start], node_geoms[end]]),
            }
        )

    # Nodes are WGS84 lon/lat; build in 4326 then reproject to the pipeline CRS.
    road_links = gpd.GeoDataFrame(rows, crs=SOURCE_CRS).to_crs(OUTPUT_CRS)
    out = toy_data_dir / "inputs" / "networks" / "faf5" / "faf5_road_links.gpq"
    out.parent.mkdir(parents=True, exist_ok=True)
    road_links.to_parquet(out)

    passenger = read_tntp_trips(TESTBED.trips_path(), node_id_formatter=_node_id)
    scaled_passenger = float(passenger["Car21"].sum()) * DEMAND_SCALE
    scaled_freight = scaled_passenger * FREIGHT_SHARE_OF_PASSENGER

    depth_by_edge = _graded_depths(flooded_edge_ids) if heterogeneous else None

    spec = SiouxFallsSpec(
        origin_node=_node_id(10),
        destination_node=_node_id(24),
        flooded_edge_ids=tuple(flooded_edge_ids),
        bridge_edge_ids=tuple(bridge_edge_ids),
        reroute_gain_edge_ids=tuple(reroute_gain_edge_ids),
        link_count=len(road_links),
        scaled_passenger_demand=scaled_passenger,
        scaled_freight_demand=scaled_freight,
        flood_depth_by_edge=depth_by_edge,
    )
    return road_links, spec


def write_od_matrices(toy_data_dir: Path) -> None:
    passenger = read_tntp_trips(TESTBED.trips_path(), node_id_formatter=_node_id)
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
    depth_by_edge: dict[str, float] | None = None,
) -> None:
    """Rasterize a full-network extent grid; only the flooded interiors get depth > 0.

    ``depth_by_edge`` (heterogeneous variant) burns a per-edge graded depth so the
    corridor spans minor->severe damage; otherwise every flooded edge gets the
    single ``FLOOD_DEPTH_M`` toy depth.
    """
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
    for e_id, geom in zip(flooded["e_id"], flooded.geometry):
        depth = (
            float(depth_by_edge.get(e_id, FLOOD_DEPTH_M))
            if depth_by_edge
            else FLOOD_DEPTH_M
        )
        start = geom.interpolate(start_frac, normalized=True)
        end = geom.interpolate(end_frac, normalized=True)
        interior = LineString([(start.x, start.y), (end.x, end.y)])
        shapes.append((interior.buffer(hazard_buffer_m), depth))

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


def write_snow_hazard_raster(
    toy_data_dir: Path,
    road_links: gpd.GeoDataFrame,
    flooded_edge_ids: tuple[str, ...],
    *,
    resolution_m: float = 10.0,
    interior_fraction: tuple[float, float] = (0.35, 0.65),
    peak_depth_mm: float = SNOW_DEPTH_MM,
) -> None:
    """Rasterize bridge interior snow depth (mm) for the Sioux Falls snow testbed."""
    flooded = road_links.loc[road_links["e_id"].isin(flooded_edge_ids)]
    if flooded.empty:
        raise ValueError("No flooded Sioux Falls bridge edges found for snow raster")

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
        shapes.append((interior.buffer(hazard_buffer_m), peak_depth_mm))

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
            hazard_dir / f"snow_hazard_141node_{variant}.tif",
            "w",
            **profile,
        ) as dst:
            dst.write(data.astype("float32"), 1)


def build_sioux_falls_dataset(
    tmp_path: Path,
    *,
    hazard: str = "flood",
    heterogeneous: bool = False,
) -> tuple[Path, SiouxFallsSpec, gpd.GeoDataFrame]:
    """Build the Sioux Falls testbed.

    ``heterogeneous=True`` (opt-in; used by the sensitivity runner) diversifies
    link lanes/width/class and floods a graded multi-link corridor so the Morris
    sensitivity panels are not degenerate. The default (False) build is byte
    identical to before, so the pinned pipeline tests are unaffected.
    """
    toy_data_dir = tmp_path / "toy_data"
    toy_data_dir.mkdir(parents=True, exist_ok=True)

    road_links, spec = write_road_links(toy_data_dir, heterogeneous=heterogeneous)
    write_od_matrices(toy_data_dir)
    copy_parameters(toy_data_dir)
    write_recovery_table(toy_data_dir)
    write_sioux_falls_damage_workbooks(toy_data_dir)
    write_study_area(toy_data_dir, road_links)
    if hazard == "snow":
        write_snow_hazard_raster(
            toy_data_dir,
            road_links,
            spec.flooded_edge_ids,
            resolution_m=10.0,
        )
    else:
        write_hazard_raster(
            toy_data_dir,
            road_links,
            spec.flooded_edge_ids,
            resolution_m=10.0,
            depth_by_edge=spec.flood_depth_by_edge,
        )
    config_path = write_toy_config(tmp_path, toy_data_dir)
    return config_path, spec, road_links


def sioux_falls_env(
    tmp_path: Path,
    config_path: Path,
    *,
    hazard: str = "flood",
) -> dict[str, str]:
    env = pipeline_env(tmp_path, config_path, network_name="sioux_falls")
    env["NIRD_TESTBED"] = "1"
    if hazard == "snow":
        env["RESIFLOW_HAZARD_TYPE"] = "snow"
    return env


def run_snow_pipeline_scripts(env: dict[str, str], *, snow_key_mm: int = SNOW_SCENARIO_KEY_MM) -> None:
    run_script("1_network_flow_model_revision.py", ["1", "1"], env)
    run_script("2_intersection_analysis.py", [str(snow_key_mm), "1"], env)
    run_script("3_damage_analysis.py", [], env)
    run_script(
        "4_rerouting_and_recovery_scenario_loop.py",
        [str(snow_key_mm), "1", "1", "1"],
        env,
    )
