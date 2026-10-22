#!/usr/bin/env python3
"""Recompute and persist the county-connector overload check.

Confirms/refreshes the finding behind
docs/FAF5_Caliper_Methodology_and_Proposed_Assignment.md: today's assignment
loads an entire county's total demand (inbound + outbound) through a single
network node's connector edges. For each county node, compares total demand
against the SUM of ORIGINAL capacity of all edges touching that node --
original capacity must come from a fresh resiflow.road_revised-style
edge_init() call, never a post-Pass-A acc_capacity column (that column is
decremented every iteration and reflects REMAINING, not original, capacity).

Writes a durable CSV (county_fips, state_abbr, overload_ratio, total_demand,
total_connector_capacity) instead of leaving results in a login-node script
that can be OOM-killed before anything is saved -- the prior interactive run
lost its final aggregate-impact number this way.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

import resiflow.road_revised as func  # noqa: E402
from resiflow.networks import load_assignment_profiles, normalize_network_links  # noqa: E402

LOGGER = logging.getLogger(__name__)

# Standard FIPS state-code -> USPS abbreviation (CONUS + DC; no territories).
_FIPS_TO_STATE = {
    "01": "al", "02": "ak", "04": "az", "05": "ar", "06": "ca", "08": "co",
    "09": "ct", "10": "de", "11": "dc", "12": "fl", "13": "ga", "15": "hi",
    "16": "id", "17": "il", "18": "in", "19": "ia", "20": "ks", "21": "ky",
    "22": "la", "23": "me", "24": "md", "25": "ma", "26": "mi", "27": "mn",
    "28": "ms", "29": "mo", "30": "mt", "31": "ne", "32": "nv", "33": "nh",
    "34": "nj", "35": "nm", "36": "ny", "37": "nc", "38": "nd", "39": "oh",
    "40": "ok", "41": "or", "42": "pa", "44": "ri", "45": "sc", "46": "sd",
    "47": "tn", "48": "tx", "49": "ut", "50": "vt", "51": "va", "53": "wa",
    "54": "wv", "55": "wi", "56": "wy",
}


def county_fips_to_state_abbr(county_fips: str) -> str:
    return _FIPS_TO_STATE.get(str(county_fips).zfill(5)[:2], "")


def compute_node_demand(od: pd.DataFrame, demand_column: str = "Car21") -> pd.Series:
    """Total inbound + outbound demand per node."""
    outbound = od.groupby("origin_node")[demand_column].sum()
    inbound = od.groupby("destination_node")[demand_column].sum()
    return outbound.add(inbound, fill_value=0.0)


def compute_node_connector_capacity(road_links: pd.DataFrame, county_node_ids: set[str]) -> pd.Series:
    """Sum of ORIGINAL (undecremented) capacity of every edge touching a county node."""
    touching = road_links[
        road_links["from_id"].astype(str).isin(county_node_ids) | road_links["to_id"].astype(str).isin(county_node_ids)
    ]
    long = pd.concat(
        [
            touching[["from_id", "acc_capacity"]].rename(columns={"from_id": "node_id"}),
            touching[["to_id", "acc_capacity"]].rename(columns={"to_id": "node_id"}),
        ]
    )
    long["node_id"] = long["node_id"].astype(str)
    return long.groupby("node_id")["acc_capacity"].sum()


def build_overload_table(
    demand_by_node: pd.Series,
    capacity_by_node: pd.Series,
) -> pd.DataFrame:
    merged = pd.DataFrame({"total_demand": demand_by_node}).join(
        pd.DataFrame({"total_connector_capacity": capacity_by_node}), how="inner"
    )
    merged["overload_ratio"] = merged["total_demand"] / merged["total_connector_capacity"].replace(0, pd.NA)
    merged = merged.reset_index().rename(columns={"index": "county_fips"})
    merged["county_fips"] = merged["county_fips"].astype(str).str.zfill(5)
    merged["state_abbr"] = merged["county_fips"].map(county_fips_to_state_abbr)
    return merged.sort_values("overload_ratio", ascending=False).reset_index(drop=True)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--road-links", required=True, help="Raw faf5_road_links.gpq (from_id/to_id/geometry/hpms_fclass); capacity is computed fresh via edge_init, never read from a post-assignment column")
    parser.add_argument("--params-root", required=True, help="Directory with flow_breakpoint_dict.json etc. (base_path/parameters)")
    parser.add_argument("--assignment-od", required=True, help="Current single-node assignment OD (origin_node,destination_node,Car21)")
    parser.add_argument("--demand-column", default="Car21")
    parser.add_argument("--output", required=True, help="Output CSV: county_fips,state_abbr,overload_ratio,total_demand,total_connector_capacity")
    parser.add_argument("--overload-threshold", type=float, default=2.0, help="Min overload_ratio to flag as a remedy target")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    args = build_arg_parser().parse_args(argv)

    LOGGER.info("Reading road links: %s", args.road_links)
    road_link_file = gpd.read_parquet(args.road_links)
    road_link_file = normalize_network_links(road_link_file, params_root=args.params_root)

    LOGGER.info("Computing ORIGINAL (pre-assignment) capacity via edge_init: %s", args.params_root)
    profiles = load_assignment_profiles(args.params_root)
    road_links = func.edge_init(
        road_link_file,
        profiles["flow_breakpoint"],
        profiles["flow_cap_plph"],
        profiles["free_flow_speed"],
        profiles["urban_speed_cap"],
        profiles["min_speed_cap"],
        max_flow_speed_dict=None,
    )

    LOGGER.info("Reading assignment OD: %s", args.assignment_od)
    od = pd.read_parquet(args.assignment_od)

    county_node_ids = set(pd.concat([od["origin_node"], od["destination_node"]]).astype(str).unique())
    LOGGER.info("Found %d unique assignment nodes (== county nodes under today's single-node mapping)", len(county_node_ids))

    demand_by_node = compute_node_demand(od, demand_column=args.demand_column)
    capacity_by_node = compute_node_connector_capacity(road_links, county_node_ids)
    overload = build_overload_table(demand_by_node, capacity_by_node)

    total_demand = overload["total_demand"].sum()
    targets = overload[overload["overload_ratio"] >= args.overload_threshold]
    excess_demand = (targets["total_demand"] - targets["total_connector_capacity"]).clip(lower=0).sum()
    LOGGER.info(
        "Counties over capacity (ratio>=%.1f): %d / %d (%.1f%%). "
        "Excess demand at these counties: %.1f (%.2f%% of national total demand %.1f)",
        args.overload_threshold,
        len(targets),
        len(overload),
        100.0 * len(targets) / len(overload),
        excess_demand,
        100.0 * excess_demand / total_demand,
        total_demand,
    )

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    overload.to_csv(args.output, index=False)
    LOGGER.info("Wrote %d rows to %s", len(overload), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
