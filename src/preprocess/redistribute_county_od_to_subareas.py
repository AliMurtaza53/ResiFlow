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


def replace_intra_county_pairs(
    county_od: pd.DataFrame,
    real_intra_county_od: pd.DataFrame,
    home_crosswalk: pd.DataFrame,
    work_crosswalk: pd.DataFrame,
    demand_column: str = "Car21",
    origin_col: str = "origin_county",
    destination_col: str = "destination_county",
    target_counties: set[str] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Swap each target county's independent-weight diagonal row for the
    REAL (non-independent) home-work pair breakdown.

    The independent split (origin_weight * destination_weight) assumes
    home and work locations are statistically independent within a
    county -- true only by approximation. For a county's own diagonal
    (home county == work county), LODES OD's real block pairs are
    available directly (build_intra_county_real_pair_od), so use those
    instead of the approximation.

    Rescales the real pairs to match each removed diagonal row's
    original total EXACTLY, preserving this module's total-demand
    invariant even though the real block-pair sum (a slightly different
    LODES read path) may not match the county-level total bit for bit.

    ``target_counties``, when given, is the authoritative set of counties
    that MUST have real pairs available -- a target missing from
    real_intra_county_od then raises instead of silently keeping that
    county's independent-weight diagonal row. Left as None (the
    inference used before this parameter existed), a target absent from
    the real pairs is invisible and its diagonal is silently left alone,
    which can hide a genuine data gap.

    Returns (county_od with target counties' own diagonal rows removed,
    real_intra_county_od rescaled and ready to concatenate onto
    redistribute()'s output).
    """
    if real_intra_county_od.empty:
        return county_od, real_intra_county_od

    node_to_county = (
        pd.concat([home_crosswalk[["node_id", "county_fips"]], work_crosswalk[["node_id", "county_fips"]]])
        .drop_duplicates("node_id")
        .set_index("node_id")["county_fips"]
    )
    real = real_intra_county_od.copy()
    real["county_fips"] = real["origin_node"].map(node_to_county)

    if target_counties is None:
        target_counties = set(real["county_fips"].dropna().unique())
    is_target_diagonal = county_od[origin_col].isin(target_counties) & (
        county_od[origin_col] == county_od[destination_col]
    )
    diagonal_totals = county_od.loc[is_target_diagonal].groupby(origin_col)[demand_column].sum()
    remaining_county_od = county_od.loc[~is_target_diagonal]

    real_totals = real.groupby("county_fips")["Car21"].sum()
    missing_real = set(diagonal_totals.index) - set(real_totals.index)
    if missing_real:
        raise ValueError(f"No real intra-county pairs found for target counties: {sorted(missing_real)} -- cannot rescale")

    scale = diagonal_totals / real_totals.reindex(diagonal_totals.index)
    real["Car21"] = real["Car21"] * real["county_fips"].map(scale)

    return remaining_county_od, real[["origin_node", "destination_node", "Car21"]]


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
    parser.add_argument(
        "--intra-county-od",
        default=None,
        help="Optional: build_passenger_subareas.py's --intra-county-output. When given, each "
        "target county's own diagonal row is replaced with these REAL (non-independent) "
        "home-work pairs instead of the independent w^H*w^W approximation.",
    )
    parser.add_argument("--demand-column", default="Car21")
    parser.add_argument("--origin-column", default="origin_county")
    parser.add_argument("--destination-column", default="destination_county")
    parser.add_argument("--output", required=True, help="New assignment OD parquet: origin_node,destination_node,Car21")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    args = build_arg_parser().parse_args(argv)

    county_od = pd.read_parquet(args.county_od)
    multinode_crosswalk = pd.read_csv(args.multinode_crosswalk, dtype={"county_fips": str, "node_id": str})
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
        destination_multinode_crosswalk = pd.read_csv(args.destination_multinode_crosswalk, dtype={"county_fips": str, "node_id": str})
        destination_full_crosswalk = build_full_crosswalk(destination_multinode_crosswalk, existing_crosswalk)

    rescaled_real_intra_county = None
    if args.intra_county_od:
        real_intra_county_od = pd.read_csv(args.intra_county_od, dtype={"origin_node": str, "destination_node": str})
        county_od, rescaled_real_intra_county = replace_intra_county_pairs(
            county_od,
            real_intra_county_od,
            multinode_crosswalk,
            destination_multinode_crosswalk if destination_multinode_crosswalk is not None else multinode_crosswalk,
            demand_column=args.demand_column,
            origin_col=args.origin_column,
            destination_col=args.destination_column,
            target_counties=set(multinode_crosswalk["county_fips"]),
        )
        LOGGER.info(
            "Replaced target counties' diagonal rows with %d real intra-county node-pair rows (total=%.1f)",
            len(rescaled_real_intra_county),
            rescaled_real_intra_county["Car21"].sum(),
        )

    new_od = redistribute(
        county_od,
        full_crosswalk,
        demand_column=args.demand_column,
        origin_col=args.origin_column,
        destination_col=args.destination_column,
        destination_crosswalk=destination_full_crosswalk,
    )
    if args.demand_column != "Car21":
        # Script 1's assignment-OD convention is always Car21, regardless of
        # the source county_od's own flow column name (e.g. passenger OD's
        # "jobs").
        new_od = new_od.rename(columns={args.demand_column: "Car21"})

    if rescaled_real_intra_county is not None:
        new_od = pd.concat([new_od, rescaled_real_intra_county], ignore_index=True)
        new_od = new_od.groupby(["origin_node", "destination_node"], as_index=False)["Car21"].sum()

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    new_od.to_parquet(args.output, index=False)
    LOGGER.info("Wrote %d assignment OD rows to %s", len(new_od), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
