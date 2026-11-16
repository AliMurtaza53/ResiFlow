"""Build the aggregate Harvey-15 county/sub-county sensitivity ODs."""
import argparse
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyogrio
import shapely
from pyproj import Geod

OD_KEYS = ["origin_node", "destination_node"]
GEOD = Geod(ellps="WGS84")


def directional_centroids(gdb, review):
    links = pyogrio.read_dataframe(gdb, layer="FAF5_Links", columns=["ID", "Class"])
    nodes = pyogrio.read_dataframe(gdb, layer="FAF5_Nodes", columns=["CentroidID"])
    if len(nodes) != 2 * len(links):
        raise ValueError("Expected one native node row per link end")
    rows = np.flatnonzero(links.Class.eq(50))
    lines = links.geometry.values[rows]
    first = shapely.get_point(shapely.get_geometry(lines, 0), 0)
    last = shapely.get_point(shapely.get_geometry(lines, shapely.get_num_geometries(lines) - 1), -1)
    a, b = nodes.iloc[2 * rows], nodes.iloc[2 * rows + 1]
    if not (shapely.equals(first, a.geometry.values).all()
            and shapely.equals(last, b.geometry.values).all()):
        raise ValueError("Native node rows do not match the ordered Class 50 endpoints")
    is_a = a.CentroidID.notna().to_numpy()
    if not np.all(is_a ^ b.CentroidID.notna().to_numpy()):
        raise ValueError("Each connector must have one centroid endpoint")
    direction = pd.DataFrame({
        "link_id": links.ID.iloc[rows].to_numpy(),
        "centroid_id": np.where(is_a, a.CentroidID.to_numpy(), b.CentroidID.to_numpy()).astype(int),
        "is_a": is_a,
    })
    result = pyogrio.read_dataframe(review, layer="faf5_native_connectors_2022", read_geometry=False)
    data = direction.merge(result, on=["link_id", "centroid_id"], validate="one_to_one")
    if len(data) != len(direction) or len(data) != 3795:
        raise ValueError("Official connector inventory does not reconcile")
    for market in ("all", "domestic", "import", "export"):
        ab, ba = data[f"{market}_ab_trips_day"], data[f"{market}_ba_trips_day"]
        data[f"{market}_out"] = np.where(data.is_a, ab, ba)
        data[f"{market}_in"] = np.where(data.is_a, ba, ab)
    fields = [f"{m}_{d}" for m in ("all", "domestic", "import", "export") for d in ("out", "in")]
    return data.groupby("centroid_id")[fields].sum(min_count=1)


def weights(counties, keys, directional, parent_rule):
    split = keys[keys.centroid_id.ge(1000000)].assign(
        county_fips=lambda x: x.centroid_id // 1000
    ).groupby("county_fips").centroid_id.agg(list).to_dict()
    rows = []
    for county, old in counties[["county_fips", "node_id"]].itertuples(index=False, name=None):
        if county not in split:
            rows.append((old, county, 1.0, 1.0, "parent_only"))
            continue
        children = split[county]
        flows = directional.loc[[county, *children], ["all_out", "all_in"]].copy()
        rule = "published"
        if flows.loc[county].isna().all():
            flows.loc[county] = 0.0 if parent_rule == "zero" else flows.loc[children].mean()
            rule = "missing_parent_" + parent_rule
        if flows.isna().any().any() or flows.lt(0).any().any() or flows.sum().le(0).any():
            raise ValueError(f"Unresolved directional weights for county {county}")
        shares = flows / flows.sum()
        rows.extend((old, c, o, i, rule) for c, o, i in shares.itertuples())
    nodes = pd.DataFrame(rows, columns=["node_id", "centroid_id", "out_share", "in_share", "rule"])
    nodes = nodes.merge(keys, on="centroid_id", how="left", validate="one_to_one")
    if nodes.centroid_node.isna().any():
        raise ValueError("Some allocation centroids are absent from the pilot network")
    nodes.centroid_node = nodes.centroid_node.astype(int)
    np.testing.assert_allclose(nodes.groupby("node_id")[["out_share", "in_share"]].sum(), 1.0)
    return nodes


def weighted_haul(frame, points, origin, destination, flow):
    start = points.loc[frame[origin]]
    end = points.loc[frame[destination]]
    miles = GEOD.inv(start.x.to_numpy(), start.y.to_numpy(), end.x.to_numpy(), end.y.to_numpy())[2] / 1609.344
    if not np.isfinite(miles).all():
        raise ValueError("Nonfinite haul")
    return float(np.average(miles, weights=frame[flow]))


def build(od, allocation, roads, centroids, counties):
    origins = allocation[allocation.out_share.gt(0)][["node_id", "centroid_node", "out_share"]]
    dests = allocation[allocation.in_share.gt(0)][["node_id", "centroid_node", "in_share"]]
    expanded = od.merge(origins.rename(columns={"node_id": "origin_node", "centroid_node": "o"}),
                        on="origin_node", how="left")
    expanded = expanded.merge(dests.rename(columns={"node_id": "destination_node", "centroid_node": "d"}),
                              on="destination_node", how="left")
    if expanded[["o", "d", "out_share", "in_share"]].isna().any().any():
        raise ValueError("Unmapped original OD endpoints")
    expanded["trips"] = expanded.Car21 * expanded.out_share * expanded.in_share
    base = od.groupby(OD_KEYS).Car21.sum().sort_index()
    rolled = expanded.groupby(OD_KEYS).trips.sum().sort_index()
    pd.testing.assert_index_equal(base.index, rolled.index)
    np.testing.assert_allclose(rolled, base, rtol=1e-9, atol=0)
    control = od.origin_node.ne(od.destination_node)
    allocated = expanded.origin_node.ne(expanded.destination_node)
    metrics = {}
    for label, county in (("Harvey15", None), ("LA", 6037), ("Harris", 48201)):
        road_node = counties.loc[counties.county_fips.eq(county), "node_id"]
        mask = control if county is None else control & (
            od.origin_node.isin(road_node) | od.destination_node.isin(road_node))
        fitted_mask = allocated if county is None else allocated & (
            expanded.origin_node.isin(road_node) | expanded.destination_node.isin(road_node))
        old = weighted_haul(od[mask], roads, *OD_KEYS, "Car21")
        new = weighted_haul(expanded[fitted_mask], centroids, "o", "d", "trips")
        metrics[label] = {"control_mi": old, "fitted_mi": new,
                          "low_mi": old * .98, "high_mi": old * 1.02,
                          "change_percent": (new / old - 1) * 100,
                          "within_2_percent": bool(.98 * old <= new <= 1.02 * old)}
    output = expanded.groupby(["o", "d"], as_index=False).trips.sum()
    output.columns = [*OD_KEYS, "Car21"]
    # Test 1 removes same-node pairs before routing. Retain their full allocation
    # in the sensitivity output, and compare assignment on the original routable scope.
    routable = expanded.loc[allocated].groupby(["o", "d"], as_index=False).trips.sum()
    routable.columns = [*OD_KEYS, "Car21"]
    np.testing.assert_allclose(routable.Car21.sum(), od.loc[control, "Car21"].sum(),
                               rtol=1e-9, atol=0)
    if routable.origin_node.eq(routable.destination_node).any():
        raise ValueError("An original inter-county trip collapsed onto one centroid")
    metrics.update(rows=len(output), trips=float(output.Car21.sum()),
                   assignment_rows=len(routable), assignment_trips=float(routable.Car21.sum()),
                   new_intercentroid_same_county_trips=float(
                       expanded.loc[~allocated & expanded.o.ne(expanded.d), "trips"].sum()))
    return output, routable, metrics


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ("gdb", "review", "inputs", "output"):
        parser.add_argument(arg, type=Path)
    args = parser.parse_args()
    od = pd.read_parquet(args.inputs / "faf5_od_matrix_subset.pq")
    if set(od.columns) != {*OD_KEYS, "Car21"} or od.Car21.isna().any() or od.Car21.lt(0).any():
        raise ValueError("Expected the aggregate, nonnegative Harvey-15 OD")
    od[OD_KEYS] = od[OD_KEYS].astype(int)
    counties = pd.read_csv(args.inputs / "county_node_crosswalk_subset.csv")
    if not counties.county_fips.is_unique or not counties.node_id.is_unique:
        raise ValueError("Expected a one-to-one Harvey-15 county crosswalk")
    keys = pd.read_csv(args.inputs / "connector_crosswalk.csv")[["centroid_id", "centroid_node"]].drop_duplicates()
    roads = gpd.read_parquet(args.inputs / "hopper_road_nodes.gpq").to_crs(4326).set_index("node_id").geometry
    centroids = pyogrio.read_dataframe(args.review, layer="faf5_centroids_2022").to_crs(4326)
    centroids = centroids.merge(keys, on="centroid_id", validate="one_to_one").set_index("centroid_node").geometry
    directional = directional_centroids(args.gdb, args.review)
    args.output.mkdir(parents=True, exist_ok=False)
    directional.to_csv(args.output / "directional_centroid_totals.csv")
    report = {}
    for rule in ("zero", "mean"):
        allocation = weights(counties, keys, directional, rule)
        output, routable, metrics = build(od, allocation, roads, centroids, counties)
        metrics["split_counties"] = int(allocation.groupby("node_id").size().gt(1).sum())
        report[rule] = metrics
        output.to_parquet(args.output / f"harvey15_cs_parent_{rule}.pq", index=False)
        routable.to_parquet(args.output / f"harvey15_cs_assignment_parent_{rule}.pq", index=False)
        allocation.to_csv(args.output / f"weights_parent_{rule}.csv", index=False)
    summary = json.dumps(report, indent=2)
    (args.output / "preflight.json").write_text(summary + "\n")
    print(summary)


if __name__ == "__main__":
    main()
