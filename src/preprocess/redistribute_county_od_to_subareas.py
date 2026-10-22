"""Redistribute county-to-county freight OD across multi-subarea nodes.

Implements the FAF5_Caliper_Methodology_and_Proposed_Assignment.md Section 4C
preservation rule:

    T_abg = T_ijg * w^O_a|ig * w^D_b|jg,   sum_{a,b} T_abg = T_ijg

County-to-county totals (T_ijg, read from the existing pre-node-mapping
county OD parquet) are held EXACTLY fixed; only where within each county the
demand enters the network changes. Counties outside the bottleneck remedy
set keep their existing single-node crosswalk (weight=1), so this produces a
full CONUS assignment OD that differs from today's only at the ~166-306
counties the connector-capacity check flagged as overloaded.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

LOGGER = logging.getLogger(__name__)


def build_full_crosswalk(
    multinode_crosswalk: pd.DataFrame,
    existing_single_node_crosswalk: pd.DataFrame,
) -> pd.DataFrame:
    """Merge multi-subarea crosswalk (bottleneck counties) with the existing
    single-node crosswalk (everyone else) into one county_fips -> [(node_id, weight)] table."""
    multi = multinode_crosswalk[["county_fips", "node_id", "weight"]].copy()
    multi["node_id"] = multi["node_id"].astype(str)
    remedied_counties = set(multi["county_fips"])

    existing = existing_single_node_crosswalk.copy()
    county_col = "county_id" if "county_id" in existing.columns else "detail_zone_id"
    node_col = "node_id" if "node_id" in existing.columns else "assigned_node_id"
    existing = existing.rename(columns={county_col: "county_fips", node_col: "node_id"})
    existing["node_id"] = existing["node_id"].astype(str)
    existing = existing[~existing["county_fips"].isin(remedied_counties)][["county_fips", "node_id"]]
    existing["weight"] = 1.0

    full = pd.concat([multi, existing], ignore_index=True)
    weight_sums = full.groupby("county_fips")["weight"].sum()
    bad = weight_sums[(weight_sums - 1.0).abs() > 1e-6]
    if not bad.empty:
        raise ValueError(f"Crosswalk weights do not sum to 1.0 for counties: {bad.to_dict()}")
    return full


def redistribute(
    county_od: pd.DataFrame,
    full_crosswalk: pd.DataFrame,
    demand_column: str = "Car21",
    origin_col: str = "origin_county",
    destination_col: str = "destination_county",
    destination_crosswalk: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Tri-proportionally split county-pair demand across subarea node pairs.

    For passenger (commute) demand, origin and destination subareas are NOT
    symmetric: a county's outbound/home-end weights (where residents live)
    differ from its inbound/work-end weights (where jobs are) -- pass
    ``destination_crosswalk`` separately in that case. Freight demand has no
    such distinction, so it reuses ``full_crosswalk`` for both sides by
    default.
    """
    origin_weights = full_crosswalk.rename(
        columns={"county_fips": origin_col, "node_id": "origin_node", "weight": "origin_weight"}
    )
    destination_source = destination_crosswalk if destination_crosswalk is not None else full_crosswalk
    destination_weights = destination_source.rename(
        columns={"county_fips": destination_col, "node_id": "destination_node", "weight": "destination_weight"}
    )

    before_total = county_od[demand_column].sum()

    expanded = county_od.merge(origin_weights, on=origin_col, how="inner")
    expanded = expanded.merge(destination_weights, on=destination_col, how="inner")
    expanded[demand_column] = expanded[demand_column] * expanded["origin_weight"] * expanded["destination_weight"]

    result = (
        expanded.groupby(["origin_node", "destination_node"], as_index=False)[demand_column]
        .sum()
    )

    after_total = result[demand_column].sum()
    if abs(after_total - before_total) > max(1e-6, before_total * 1e-6):
        raise ValueError(
            f"Demand total not preserved: before={before_total:.6f} after={after_total:.6f} "
            f"(delta={after_total - before_total:.6f}). Check for counties dropped by inner merges."
        )
    LOGGER.info("Preserved total demand: %.2f (before) == %.2f (after)", before_total, after_total)
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--county-od", required=True, help="County-to-county OD parquet (pre-node-mapping)")
    parser.add_argument("--multinode-crosswalk", required=True, help="Output of build_multinode_county_subareas.py (origin side; also destination side unless --destination-multinode-crosswalk is given)")
    parser.add_argument(
        "--destination-multinode-crosswalk",
        default=None,
        help="Optional separate multi-subarea crosswalk for the destination side (e.g. work-weighted vs origin's home-weighted) -- passenger demand only",
    )
    parser.add_argument("--existing-crosswalk", required=True, help="Existing single-node bts_county_to_network_centroid crosswalk")
    parser.add_argument("--demand-column", default="Car21")
    parser.add_argument("--origin-column", default="origin_county")
    parser.add_argument("--destination-column", default="destination_county")
    parser.add_argument("--output", required=True, help="New assignment OD parquet: origin_node,destination_node,Car21")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    args = build_arg_parser().parse_args(argv)

    county_od = pd.read_parquet(args.county_od)
    multinode_crosswalk = pd.read_csv(args.multinode_crosswalk, dtype={"county_fips": str})
    existing_crosswalk = pd.read_csv(args.existing_crosswalk, dtype=str)

    full_crosswalk = build_full_crosswalk(multinode_crosswalk, existing_crosswalk)
    LOGGER.info(
        "Full crosswalk: %d counties, %d county->node rows (%d remedied with >1 node)",
        full_crosswalk["county_fips"].nunique(),
        len(full_crosswalk),
        full_crosswalk.groupby("county_fips").size().gt(1).sum(),
    )

    destination_full_crosswalk = None
    if args.destination_multinode_crosswalk:
        destination_multinode_crosswalk = pd.read_csv(args.destination_multinode_crosswalk, dtype={"county_fips": str})
        destination_full_crosswalk = build_full_crosswalk(destination_multinode_crosswalk, existing_crosswalk)

    new_od = redistribute(
        county_od,
        full_crosswalk,
        demand_column=args.demand_column,
        origin_col=args.origin_column,
        destination_col=args.destination_column,
        destination_crosswalk=destination_full_crosswalk,
    )

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    new_od.to_parquet(args.output, index=False)
    LOGGER.info("Wrote %d assignment OD rows to %s", len(new_od), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
