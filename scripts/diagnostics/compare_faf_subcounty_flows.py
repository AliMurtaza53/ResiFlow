"""Compare paired Harvey-15 accumulated link flows with published FAF5."""
import argparse
from pathlib import Path
import sqlite3

import numpy as np
import pandas as pd

ARMS = ("parent_only", "zero", "mean")


def metrics(frame, scope):
    for arm in ARMS:
        data = frame[["official", arm]].dropna()
        if data.empty:
            continue
        official = data.official
        modeled = data[arm]
        denom = official.sum()
        yield {
            "scope": scope, "arm": arm, "links_native": len(frame),
            "links_compared": len(data), "links_missing_official": int(frame.official.isna().sum()),
            "published_zeros_compared": int(official.eq(0).sum()),
            "official_trips_day": denom, "modeled_trips_day": modeled.sum(),
            "modeled_to_official_ratio": modeled.sum() / denom if denom else np.nan,
            "modeled_trips_on_missing_official": frame.loc[frame.official.isna(), arm].sum(),
            "pearson": modeled.corr(official) if modeled.nunique() > 1 and official.nunique() > 1 else np.nan,
            "weighted_absolute_relative_error": (modeled - official).abs().sum() / denom if denom else np.nan,
        }


def read_native_reference(review, native_gdb):
    import pyogrio

    with sqlite3.connect(review.resolve().as_uri() + "?mode=ro", uri=True) as db:
        roads = pd.read_sql_query("""
            SELECT link_id, faf5_class, STATE, all_tot_trips_day AS official
            FROM resiflow_roads_official_faf5_flows
        """, db)
        links = pd.read_sql_query("""
            SELECT link_id, centroid_id, [group] AS node_type, all_tot_trips_day AS official
            FROM faf5_native_connectors_2022
        """, db)
    county_keys = pyogrio.read_dataframe(native_gdb, layer="FAF5_Links",
                                         columns=["ID", "CTFIPS"], read_geometry=False)
    roads = roads.merge(county_keys.rename(columns={"ID": "link_id"}),
                        on="link_id", how="left", validate="one_to_one")
    return roads, links


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review", type=Path, help="Review GeoPackage or directory of flat references")
    parser.add_argument("runs", type=Path)
    parser.add_argument("native_gdb", nargs="?", type=Path)
    args = parser.parse_args()
    if args.review.is_dir():
        roads = pd.read_parquet(args.review / "official_roads.pq")
        links = pd.read_parquet(args.review / "official_connectors.pq")
    else:
        if args.native_gdb is None:
            parser.error("native_gdb is required with a review GeoPackage")
        roads, links = read_native_reference(args.review, args.native_gdb)
    for arm in ARMS:
        f = pd.read_parquet(args.runs / f"comparison_{arm}.pq")
        flow = f.set_index(f.e_id.astype(int), verify_integrity=True).acc_flow
        for table in (roads, links):
            table[arm] = table.link_id.map(flow)
    # Use one fixed support so each arm is scored over the same links. Roads
    # omitted from any solver output stay outside the matched comparison.
    roads = roads[roads[list(ARMS)].notna().all(axis=1)]
    links = links[links[list(ARMS)].notna().all(axis=1)]
    footprint = roads[roads[list(ARMS)].gt(0).any(axis=1)]
    rows = list(metrics(roads, "road_all_shared")) + list(metrics(footprint, "road_pilot_footprint"))
    for clazz, group in footprint.groupby("faf5_class", dropna=False):
        rows.extend(metrics(group, f"road_pilot_footprint_class_{clazz}"))
    for clazz, group in roads.groupby("faf5_class", dropna=False):
        rows.extend(metrics(group, f"road_all_class_{clazz}"))
    for state, group in roads.groupby("STATE", dropna=False):
        rows.extend(metrics(group, f"road_state_{state}"))
    county = pd.to_numeric(roads.CTFIPS, errors="coerce")
    for label, fips in (("Los Angeles", 6037), ("Harris", 48201)):
        rows.extend(metrics(roads[county.eq(fips)], f"road_{label}"))
        rows.extend(metrics(links[(links.centroid_id == fips) |
                                 (links.centroid_id // 1000 == fips)], f"connector_{label}"))
    for group_name, group in links.groupby("node_type"):
        rows.extend(metrics(group, "connector_" + group_name))
    for centroid_id, group in links.groupby("centroid_id"):
        if centroid_id in (6037, 48201) or centroid_id // 1000 in (6037, 48201):
            rows.extend(metrics(group, f"centroid_{centroid_id}"))
    output = pd.DataFrame(rows)
    output.to_csv(args.runs / "faf_comparison.csv", index=False, na_rep="NA")
    subset = output[~output.scope.str.contains("class_|centroid_|state_")]
    print(subset[["scope", "arm", "links_compared", "pearson",
                  "weighted_absolute_relative_error"]].round(4).to_string(index=False))


if __name__ == "__main__":
    main()
