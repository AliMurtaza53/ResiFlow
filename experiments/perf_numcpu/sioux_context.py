"""Build Script-1-equivalent Sioux Falls network + LCP args for perf spikes."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

import geopandas as gpd
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"
sys.path.insert(0, str(TESTS_DIR))
sys.path.insert(0, str(REPO_ROOT / "src"))

from resiflow.demand import align_od_node_dtype, demand_spec_from_env, load_assignment_demand
from resiflow.networks import load_assignment_profiles, normalize_network_links
from resiflow import road_revised as rr


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path.exists():
            return path
    return None


def build_sioux_lcp_context(
    *,
    origin_replicas: int = 1,
) -> tuple[object, list[tuple], dict[str, float | int]]:
    """Return (igraph network, lcp args, stats) using the same path as Script 1."""
    from sioux_falls_fixtures import build_sioux_falls_dataset

    with tempfile.TemporaryDirectory(prefix="perf_ctx_") as tmp_name:
        tmp = Path(tmp_name)
        config_path, _spec, _links = build_sioux_falls_dataset(tmp)
        os.environ["NIRD_CONFIG_PATH"] = str(config_path)
        from resiflow.utils import load_config

        base_path = Path(load_config()["paths"]["soge_clusters"])
        params_root = _first_existing(
            [
                base_path / "parameters",
                base_path / "inputs" / "parameters",
            ]
        )
        if params_root is None:
            raise FileNotFoundError("parameters folder not found under Sioux Falls toy layout")

        profiles = load_assignment_profiles(params_root)
        flow_breakpoint_dict = profiles["flow_breakpoint"]
        flow_capacity_dict = profiles["flow_cap_plph"]
        free_flow_speed_dict = profiles["free_flow_speed"]
        min_speed_dict = profiles["min_speed_cap"]
        urban_speed_dict = profiles["urban_speed_cap"]

        road_links_path = _first_existing(
            [
                base_path / "networks" / "faf5" / "faf5_road_links.gpq",
                base_path / "inputs" / "networks" / "faf5" / "faf5_road_links.gpq",
            ]
        )
        if road_links_path is None:
            raise FileNotFoundError("faf5_road_links.gpq not found")

        road_link_file = gpd.read_parquet(road_links_path)
        road_link_file = normalize_network_links(road_link_file, params_root=str(params_root))
        demand = load_assignment_demand(base_path, demand_spec_from_env(base_path))
        od = demand.assignment_od.copy()
        od["Car21"] = pd.to_numeric(od["Car21"], errors="coerce").fillna(0.0)
        od = align_od_node_dtype(od, road_link_file)

        road_links = rr.edge_init(
            road_link_file,
            flow_breakpoint_dict,
            flow_capacity_dict,
            free_flow_speed_dict,
            urban_speed_dict,
            min_speed_dict,
            max_flow_speed_dict=None,
        )
        network, _road_links = rr.create_igraph_network(road_links, vehicle_type="car")

        args_df = (
            od.groupby("origin_node")
            .agg(
                destinations=("destination_node", lambda s: sorted(map(str, s.tolist()))),
                flows=("Car21", lambda s: list(s.tolist())),
            )
            .reset_index()
        )
        base_args = [
            (str(row.origin_node), list(row.destinations), list(row.flows))
            for row in args_df.itertuples(index=False)
        ]
        args: list[tuple] = []
        for _rep in range(max(1, origin_replicas)):
            args.extend(base_args)

        stats = {
            "origins_unique": len(base_args),
            "origins_tasks": len(args),
            "origin_replicas": origin_replicas,
            "edges": network.ecount(),
            "od_rows": len(od),
        }
        return network, args, stats
