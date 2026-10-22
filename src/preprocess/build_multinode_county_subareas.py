"""Build multiple truck-access loading subareas per bottlenecked county.

Remedy for the county-connector funnel bottleneck confirmed in
docs/FAF5_Caliper_Methodology_and_Proposed_Assignment.md: today's assignment
OD loads an ENTIRE county's demand onto a single nearest network node,
concentrating demand onto that node's 1-6 connector edges. This module
spreads a target county's demand across several subareas located by
freight-relevant LODES WAC employment clusters, each snapped to the nearest
network node that sits on a "plausible truck-access road" (collector or
better, per resiflow.hpms_fclass assignment tiers) -- not a blind nearest-node
snap, and not local streets.

County-to-county OD totals are NOT changed here; this only produces the
crosswalk (county -> {node_id, weight}) used downstream to redistribute each
county's existing demand (see redistribute_county_od_to_subareas.py).
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

try:
    import geopandas as gpd  # type: ignore
except Exception:  # pragma: no cover
    gpd = None

from resiflow.hpms_fclass import assignment_tier_from_fclass, derive_hpms_fclass
from resiflow.lodes_wac import build_county_block_employment

LOGGER = logging.getLogger(__name__)

# Road tiers acceptable as a county-connector landing point. Excludes
# local_access (would misrepresent neighborhood streets as freight gateways)
# and freeway (would create illegal/implausible direct motorway on-ramps);
# collector/arterial match how real shippers actually reach the highway
# network per the Caliper guidance's "plausible truck-access roads" principle.
_TRUCK_ACCESS_TIERS = frozenset({"collector", "arterial"})

_MAX_SUBAREAS_PER_COUNTY = 6
_MIN_SUBAREAS_FOR_TARGET_COUNTY = 2


def subareas_for_overload_ratio(overload_ratio: float) -> int:
    """More subareas for more severely overloaded counties, capped."""
    return int(np.clip(np.ceil(overload_ratio), _MIN_SUBAREAS_FOR_TARGET_COUNTY, _MAX_SUBAREAS_PER_COUNTY))


def _weighted_kmeans(points: np.ndarray, weights: np.ndarray, k: int, *, seed: int = 0, iters: int = 50) -> np.ndarray:
    """Minimal weighted K-means (no sklearn dependency). Returns cluster labels."""
    rng = np.random.default_rng(seed)
    n = len(points)
    if k >= n:
        return np.arange(n)
    # weighted sample for initial centroids (k-means++-lite: weight-proportional pick)
    probs = weights / weights.sum()
    seed_idx = rng.choice(n, size=k, replace=False, p=probs)
    centroids = points[seed_idx].copy()
    labels = np.zeros(n, dtype=int)
    for _ in range(iters):
        dists = ((points[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
        new_labels = dists.argmin(axis=1)
        if np.array_equal(new_labels, labels) and _ > 0:
            break
        labels = new_labels
        for c in range(k):
            mask = labels == c
            if mask.any():
                centroids[c] = np.average(points[mask], axis=0, weights=weights[mask])
    return labels


def cluster_county_subareas(
    block_employment: pd.DataFrame,
    overload_ratios: pd.Series,
    weight_col: str = "freight_jobs",
) -> pd.DataFrame:
    """Cluster each county's weighted blocks (freight employment, or any
    other per-block weight -- e.g. passenger home/work counts) into subareas.

    Returns: county_fips, subarea_rank, lon, lat, weight (share within the
    county, sums to 1.0 per county).
    """
    rows: list[pd.DataFrame] = []
    for county_fips, group in block_employment.groupby("county_fips"):
        overload_ratio = float(overload_ratios.get(county_fips, _MIN_SUBAREAS_FOR_TARGET_COUNTY))
        k = subareas_for_overload_ratio(overload_ratio)
        points = group[["lon", "lat"]].to_numpy(dtype=float)
        weights = group[weight_col].to_numpy(dtype=float)
        if len(group) < k:
            k = max(1, len(group))
        labels = _weighted_kmeans(points, weights, k)
        sub = pd.DataFrame({"county_fips": county_fips, "_label": labels, "lon": points[:, 0], "lat": points[:, 1], "weight": weights})
        agg = sub.groupby("_label").apply(
            lambda g: pd.Series(
                {
                    "lon": np.average(g["lon"], weights=g["weight"]),
                    "lat": np.average(g["lat"], weights=g["weight"]),
                    "weight": g["weight"].sum(),
                }
            ),
            include_groups=False,
        ).reset_index(drop=True)
        agg["weight"] = agg["weight"] / agg["weight"].sum()
        agg = agg.sort_values("weight", ascending=False).reset_index(drop=True)
        agg["county_fips"] = county_fips
        agg["subarea_rank"] = range(len(agg))
        rows.append(agg[["county_fips", "subarea_rank", "lon", "lat", "weight"]])
    if not rows:
        return pd.DataFrame(columns=["county_fips", "subarea_rank", "lon", "lat", "weight"])
    return pd.concat(rows, ignore_index=True)


def _first_coord(geom) -> tuple[float, float]:
    """First vertex of a line geometry; descends into MultiLineString/MultiPoint,
    since real FAF5/TIGER link geometries are sometimes multi-part and
    shapely's .coords raises NotImplementedError directly on those."""
    while hasattr(geom, "geoms"):
        geom = geom.geoms[0]
    return geom.coords[0]


def snap_subareas_to_truck_access_nodes(
    subareas: pd.DataFrame,
    road_links: pd.DataFrame,
    target_crs: str = "EPSG:2163",
) -> pd.DataFrame:
    """Snap each subarea to the nearest node touching a collector/arterial link.

    road_links must carry f_class/faf5_class (or an existing hpms_fclass /
    assignment_tier column) plus from_id/to_id/geometry, matching the
    convention in resiflow.hpms_fclass and the FAF5 network build.
    """
    if gpd is None:
        raise ImportError("geopandas is required to snap subareas to network nodes")

    links = road_links.copy()
    if "assignment_tier" not in links.columns:
        if "hpms_fclass" not in links.columns:
            links["hpms_fclass"] = derive_hpms_fclass(links.get("f_class", links.get("F_Class")), links.get("faf5_class", links.get("Class")))
        links["assignment_tier"] = assignment_tier_from_fclass(links["hpms_fclass"])
    truck_access_links = links[links["assignment_tier"].isin(_TRUCK_ACCESS_TIERS)]
    node_ids = pd.unique(pd.concat([truck_access_links["from_id"], truck_access_links["to_id"]]))

    node_points = (
        links[links["from_id"].isin(node_ids)][["from_id", "geometry"]]
        .rename(columns={"from_id": "node_id"})
        .assign(geometry=lambda d: d.geometry.apply(_first_coord))
    )
    node_points["geometry"] = node_points["geometry"].apply(lambda xy: gpd.points_from_xy([xy[0]], [xy[1]])[0])
    node_gdf = gpd.GeoDataFrame(node_points, geometry="geometry", crs=links.crs or "EPSG:4326").drop_duplicates("node_id")
    node_gdf = node_gdf.to_crs(target_crs)

    subarea_gdf = gpd.GeoDataFrame(
        subareas.copy(),
        geometry=gpd.points_from_xy(subareas["lon"], subareas["lat"]),
        crs="EPSG:4326",
    ).to_crs(target_crs)

    nearest = gpd.sjoin_nearest(subarea_gdf, node_gdf[["node_id", "geometry"]], how="left", distance_col="distance_m")
    result = pd.DataFrame(nearest.drop(columns=["geometry", "index_right"], errors="ignore"))
    return result[["county_fips", "subarea_rank", "lon", "lat", "weight", "node_id", "distance_m"]]


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--target-counties-csv", required=True, help="CSV with county_fips, overload_ratio, state_abbr columns")
    parser.add_argument("--road-links", required=True, help="faf5_road_links.gpq with from_id/to_id/geometry/fclass")
    parser.add_argument("--year", type=int, default=2022)
    parser.add_argument("--lodes-job-type", default="JT00")
    parser.add_argument("--output", required=True, help="Output crosswalk CSV: county_fips,subarea_rank,node_id,weight,distance_m")
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    args = build_arg_parser().parse_args(argv)

    targets = pd.read_csv(args.target_counties_csv, dtype={"county_fips": str})
    targets["county_fips"] = targets["county_fips"].str.zfill(5)
    states = sorted(targets["state_abbr"].str.lower().unique())
    target_fips = set(targets["county_fips"])

    LOGGER.info("Building freight employment for %d target counties across %d states", len(target_fips), len(states))
    block_employment = build_county_block_employment(states, target_fips, job_type=args.lodes_job_type, year=args.year)
    LOGGER.info("Loaded %d employment blocks", len(block_employment))

    overload_ratios = targets.set_index("county_fips")["overload_ratio"]
    subareas = cluster_county_subareas(block_employment, overload_ratios)
    LOGGER.info("Clustered into %d subareas across %d counties", len(subareas), subareas["county_fips"].nunique())

    # Counties with no employment-bearing blocks (data gap) fall back to a
    # single subarea at the county's own centroid -- handled by the caller
    # via road_links absence; flagged here for visibility.
    missing = target_fips - set(subareas["county_fips"])
    if missing:
        LOGGER.warning("%d target counties had no LODES WAC employment blocks: %s", len(missing), sorted(missing)[:10])

    road_links = gpd.read_parquet(args.road_links) if gpd is not None else pd.read_parquet(args.road_links)
    snapped = snap_subareas_to_truck_access_nodes(subareas, road_links)

    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    snapped.to_csv(args.output, index=False)
    LOGGER.info("Wrote %d subarea->node rows to %s", len(snapped), args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
