"""Build home-weighted and work-weighted loading subareas for passenger demand.

Per-conversation guidance (2026-10-22): the county-connector overload check
(scripts/compute_county_connector_bottleneck.py), once corrected to use the
REAL combined freight+passenger demand, showed the overload is ~99%
commute-driven, concentrated at major metro counties -- not primarily a
freight problem. Passenger demand must NOT be disaggregated the way freight
is (employment-weighting both the origin and destination end): a commute
trip's origin should follow WHERE PEOPLE LIVE and its destination WHERE
THEY WORK, so this builds two separate per-county subarea sets from the
LODES OD files' own h_geocode (home block) / w_geocode (work block) columns
-- no employment proxy (WAC) needed, the block-level commute pairs already
carry the real home/work locations.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import pandas as pd

from preprocess.build_multinode_county_subareas import (
    cluster_county_subareas,
    snap_subareas_to_truck_access_nodes,
)
from resiflow.lodes_county_od import normalize_county_fips, read_lodes_crosswalk, read_lodes_od
from resiflow.lodes_wac import read_lodes_block_geo

LOGGER = logging.getLogger(__name__)


def build_endpoint_blocks(
    states: list[str],
    target_county_fips: set[str],
    endpoint: str,
    *,
    job_type: str = "JT00",
    year: int = 2022,
    base: str | Path | None = None,
) -> pd.DataFrame:
    """Aggregate LODES OD block pairs to one-sided (home- or work-) block weights.

    endpoint="home" sums S000 by h_geocode (where commuters live); "work"
    sums by w_geocode (where they work). Restricted to blocks inside
    target_county_fips so only the bottlenecked counties get built.
    """
    if endpoint not in ("home", "work"):
        raise ValueError(f"endpoint must be 'home' or 'work', got {endpoint!r}")
    geocode_col = "h_geocode" if endpoint == "home" else "w_geocode"

    frames: list[pd.DataFrame] = []
    for state in states:
        geo = read_lodes_crosswalk(state, base=base).rename(columns={"tabblk2020": geocode_col, "cty": "county_fips"})
        geo = geo[geo["county_fips"].isin(target_county_fips)]
        if geo.empty:
            continue
        block_latlon = read_lodes_block_geo(state, base=base).rename(columns={"tabblk2020": geocode_col})

        parts: list[pd.DataFrame] = []
        for part in ("main", "aux"):
            try:
                od = read_lodes_od(state, job_type=job_type, year=year, part=part, base=base)
            except FileNotFoundError:
                continue
            od = od.merge(geo[["county_fips", geocode_col]], on=geocode_col, how="inner")
            parts.append(od)
        if not parts:
            continue
        combined = pd.concat(parts, ignore_index=True)
        weight = (
            combined.groupby([geocode_col, "county_fips"], as_index=False)["S000"]
            .sum()
            .rename(columns={"S000": "weight"})
        )
        weight = weight.merge(block_latlon[[geocode_col, "blklondd", "blklatdd"]], on=geocode_col, how="inner")
        frames.append(weight.rename(columns={"blklondd": "lon", "blklatdd": "lat"}))

    if not frames:
        return pd.DataFrame(columns=["county_fips", "lon", "lat", "weight"])
    out = pd.concat(frames, ignore_index=True)
    return out[out["weight"] > 0][["county_fips", "lon", "lat", "weight"]]


def assign_blocks_to_nearest_subarea(
    blocks: pd.DataFrame,
    subarea_crosswalk: pd.DataFrame,
    block_id_col: str,
) -> pd.DataFrame:
    """Nearest-subarea-centroid assignment for each block, within its own county.

    blocks: county_fips, lon, lat, <block_id_col>.
    subarea_crosswalk: county_fips, lon, lat, node_id (a built home/work
    crosswalk -- lon/lat here are the SUBAREA centroid, matching how the
    block was originally clustered, not the snapped network node).
    Returns: <block_id_col>, node_id.
    """
    assignments: list[pd.DataFrame] = []
    for county_fips, group in blocks.groupby("county_fips"):
        subareas = subarea_crosswalk[subarea_crosswalk["county_fips"] == county_fips]
        if subareas.empty:
            continue
        sub_lon = subareas["lon"].to_numpy(dtype=float)
        sub_lat = subareas["lat"].to_numpy(dtype=float)
        sub_node = subareas["node_id"].to_numpy()
        blk_lon = group["lon"].to_numpy(dtype=float)
        blk_lat = group["lat"].to_numpy(dtype=float)
        dist = (blk_lon[:, None] - sub_lon[None, :]) ** 2 + (blk_lat[:, None] - sub_lat[None, :]) ** 2
        nearest_idx = dist.argmin(axis=1)
        assignments.append(
            pd.DataFrame({block_id_col: group[block_id_col].to_numpy(), "node_id": sub_node[nearest_idx]})
        )
    if not assignments:
        return pd.DataFrame(columns=[block_id_col, "node_id"])
    return pd.concat(assignments, ignore_index=True)


def build_intra_county_real_pair_od(
    states: list[str],
    target_county_fips: set[str],
    home_crosswalk: pd.DataFrame,
    work_crosswalk: pd.DataFrame,
    *,
    job_type: str = "JT00",
    year: int = 2022,
    base: str | Path | None = None,
) -> pd.DataFrame:
    """Real (non-independent) intra-county home-work node-pair demand.

    Only intra-county pairs (home county == work county == a target
    county) need this -- that is exactly the case where BOTH the origin
    and destination sides are multi-subarea, so the independent
    w^H_a * w^W_b split (used for every other county pair) would assume
    home and work locations are statistically independent within the
    county. LODES OD's own h_geocode/w_geocode pairs already carry the
    real joint structure, so this maps each real pair to its home/work
    subarea node directly instead of approximating it.

    Returns: origin_node, destination_node, Car21.
    """
    frames: list[pd.DataFrame] = []
    for state in states:
        geo = read_lodes_crosswalk(state, base=base)
        home_county = geo.rename(columns={"tabblk2020": "h_geocode", "cty": "home_county"})
        work_county = geo.rename(columns={"tabblk2020": "w_geocode", "cty": "work_county"})

        try:
            od = read_lodes_od(state, job_type=job_type, year=year, part="main", base=base)
        except FileNotFoundError:
            continue
        od = od.merge(home_county[["h_geocode", "home_county"]], on="h_geocode", how="inner")
        od = od.merge(work_county[["w_geocode", "work_county"]], on="w_geocode", how="inner")
        od = od[(od["home_county"] == od["work_county"]) & od["home_county"].isin(target_county_fips)]
        if od.empty:
            continue

        block_geo = read_lodes_block_geo(state, base=base).rename(columns={"blklondd": "lon", "blklatdd": "lat"})
        home_blocks = (
            od[["h_geocode", "home_county"]]
            .drop_duplicates()
            .rename(columns={"h_geocode": "tabblk2020", "home_county": "county_fips"})
            .merge(block_geo[["tabblk2020", "lon", "lat"]], on="tabblk2020", how="inner")
        )
        work_blocks = (
            od[["w_geocode", "work_county"]]
            .drop_duplicates()
            .rename(columns={"w_geocode": "tabblk2020", "work_county": "county_fips"})
            .merge(block_geo[["tabblk2020", "lon", "lat"]], on="tabblk2020", how="inner")
        )

        home_assignment = assign_blocks_to_nearest_subarea(home_blocks, home_crosswalk, "tabblk2020").rename(
            columns={"tabblk2020": "h_geocode", "node_id": "origin_node"}
        )
        work_assignment = assign_blocks_to_nearest_subarea(work_blocks, work_crosswalk, "tabblk2020").rename(
            columns={"tabblk2020": "w_geocode", "node_id": "destination_node"}
        )

        mapped = od.merge(home_assignment, on="h_geocode", how="inner").merge(work_assignment, on="w_geocode", how="inner")
        frames.append(mapped.groupby(["origin_node", "destination_node"], as_index=False)["S000"].sum())

    if not frames:
        return pd.DataFrame(columns=["origin_node", "destination_node", "Car21"])
    combined = pd.concat(frames, ignore_index=True)
    combined = combined.groupby(["origin_node", "destination_node"], as_index=False)["S000"].sum()
    return combined.rename(columns={"S000": "Car21"})


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target-counties-csv", required=True, help="CSV with county_fips, overload_ratio, state_abbr columns")
    parser.add_argument("--road-links", required=True, help="faf5_road_links.gpq with from_id/to_id/geometry/hpms_fclass")
    parser.add_argument("--year", type=int, default=2022)
    parser.add_argument("--lodes-job-type", default="JT00")
    parser.add_argument("--max-subareas-per-county", type=int, default=6, help="Override the default subarea cap (6), for sensitivity tests on large/dense counties")
    parser.add_argument("--home-output", required=True, help="Origin (home-weighted) crosswalk CSV")
    parser.add_argument("--work-output", required=True, help="Destination (work-weighted) crosswalk CSV")
    parser.add_argument(
        "--intra-county-output",
        default=None,
        help="Optional: real (non-independent) intra-county home-work node-pair OD CSV -- "
        "use this to REPLACE the independent w^H*w^W approximation for each target county's own diagonal",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    args = build_arg_parser().parse_args(argv)

    targets = pd.read_csv(args.target_counties_csv, dtype={"county_fips": str})
    targets["county_fips"] = targets["county_fips"].map(normalize_county_fips)
    states = sorted(targets["state_abbr"].str.lower().unique())
    target_fips = set(targets["county_fips"])
    overload_ratios = targets.set_index("county_fips")["overload_ratio"]

    import geopandas as gpd

    road_links = gpd.read_parquet(args.road_links)

    snapped_by_endpoint: dict[str, pd.DataFrame] = {}
    for endpoint, output_path in (("home", args.home_output), ("work", args.work_output)):
        LOGGER.info("Building %s-side blocks for %d target counties across %d states", endpoint, len(target_fips), len(states))
        blocks = build_endpoint_blocks(states, target_fips, endpoint, job_type=args.lodes_job_type, year=args.year)
        LOGGER.info("Loaded %d %s blocks", len(blocks), endpoint)

        subareas = cluster_county_subareas(blocks, overload_ratios, weight_col="weight", max_subareas=args.max_subareas_per_county)
        LOGGER.info("Clustered into %d %s subareas across %d counties", len(subareas), endpoint, subareas["county_fips"].nunique())

        missing = target_fips - set(subareas["county_fips"])
        if missing:
            LOGGER.warning("%d target counties had no %s-side LODES blocks: %s", len(missing), endpoint, sorted(missing))

        snapped = snap_subareas_to_truck_access_nodes(subareas, road_links)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        snapped.to_csv(output_path, index=False)
        LOGGER.info("Wrote %d %s subarea->node rows to %s", len(snapped), endpoint, output_path)
        snapped_by_endpoint[endpoint] = snapped

    if args.intra_county_output:
        LOGGER.info("Building REAL (non-independent) intra-county home-work node-pair OD")
        intra_county_od = build_intra_county_real_pair_od(
            states,
            target_fips,
            snapped_by_endpoint["home"],
            snapped_by_endpoint["work"],
            job_type=args.lodes_job_type,
            year=args.year,
        )
        Path(args.intra_county_output).parent.mkdir(parents=True, exist_ok=True)
        intra_county_od.to_csv(args.intra_county_output, index=False)
        LOGGER.info(
            "Wrote %d real intra-county node-pair rows (total Car21=%.1f) to %s",
            len(intra_county_od),
            intra_county_od["Car21"].sum() if not intra_county_od.empty else 0.0,
            args.intra_county_output,
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
