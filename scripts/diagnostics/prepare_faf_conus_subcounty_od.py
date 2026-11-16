"""Build matched CONUS first-pass inputs in bounded batches."""
import argparse
from contextlib import ExitStack
import json
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from prepare_faf_subcounty_od import GEOD, OD_KEYS, weights

ARMS = ("parent_only", "zero", "mean")


def allocate(batch, shares):
    origin = shares.loc[shares.out_share.gt(0), ["node_id", "centroid_node", "out_share"]]
    destination = shares.loc[shares.in_share.gt(0), ["node_id", "centroid_node", "in_share"]]
    x = batch.merge(origin.rename(columns={"node_id": "origin_node", "centroid_node": "o"}),
                    on="origin_node", how="left")
    x = x.merge(destination.rename(columns={"node_id": "destination_node", "centroid_node": "d"}),
                on="destination_node", how="left")
    if x[["o", "d", "out_share", "in_share"]].isna().any().any():
        raise ValueError("Missing OD endpoint mapping")
    x["trips"] = x.Car21 * x.out_share * x.in_share
    np.testing.assert_allclose(x.groupby("source_row").trips.sum().reindex(batch.source_row),
                               batch.Car21, rtol=1e-9, atol=0)
    if x.o.eq(x.d).any():
        raise ValueError("An originally routable pair became a self trip")
    return x[["o", "d", "trips"]].set_axis([*OD_KEYS, "Car21"], axis=1)


def miles_times_trips(od, coords):
    starts = coords.loc[od.origin_node]
    ends = coords.loc[od.destination_node]
    metres = GEOD.inv(starts.x.to_numpy(), starts.y.to_numpy(),
                      ends.x.to_numpy(), ends.y.to_numpy())[2]
    if not np.isfinite(metres).all():
        raise ValueError("Nonfinite haul")
    return float(np.dot(metres, od.Car21) / 1609.344)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("od", "county_crosswalk", "connector_crosswalk", "road_nodes", "references", "output"):
        parser.add_argument(name, type=Path)
    a = parser.parse_args()
    counties = pd.read_csv(a.county_crosswalk)
    keys = pd.read_csv(a.connector_crosswalk)[["centroid_id", "centroid_node"]].drop_duplicates()
    official = pd.read_csv(a.references / "directional_centroid_totals.csv", index_col="centroid_id")
    defined = counties[counties.county_fips.isin(keys.centroid_id)]
    unmatched = counties[~counties.county_fips.isin(keys.centroid_id)]
    if not defined.node_id.is_unique or set(defined.node_id) & set(unmatched.node_id):
        raise ValueError("Ambiguous mapping of corrected road nodes to official parents")
    if set(unmatched.state_fips) != {9} or len(unmatched) != 9:
        raise ValueError("Unexpected county keys without official parents")
    fallback = unmatched[["node_id"]].drop_duplicates().assign(
        centroid_node=lambda x: x.node_id, out_share=1.0, in_share=1.0, rule="keep_road_node")
    parent = defined.merge(keys, left_on="county_fips", right_on="centroid_id",
                           validate="one_to_one").assign(out_share=1.0, in_share=1.0, rule="parent_only")
    shares = {"parent_only": parent, **{r: weights(defined, keys, official, r) for r in ("zero", "mean")}}
    for arm, frame in shares.items():
        shares[arm] = pd.concat([frame, fallback], ignore_index=True)
    roads = gpd.read_parquet(a.road_nodes).to_crs(4326).set_index("node_id").geometry
    coords = pd.concat([pd.DataFrame({"x": roads.x, "y": roads.y}),
                        pd.read_csv(a.references / "centroid_coords.csv", index_col="node_id")],
                       verify_integrity=True)
    a.output.mkdir(exist_ok=False, parents=True)
    schema = pa.schema([(name, pa.int64()) for name in OD_KEYS] + [("Car21", pa.float64())])
    sums = {arm: {"rows": 0, "trips": 0., "trip_miles": 0.} for arm in ("control", *ARMS)}
    intended = {arm: set() for arm in ARMS}
    with ExitStack() as stack:
        writers = {arm: stack.enter_context(pq.ParquetWriter(a.output / f"{arm}.pq", schema))
                   for arm in ARMS}
        for block in pq.ParquetFile(a.od).iter_batches(batch_size=250000, columns=[*OD_KEYS, "Car21"]):
            frame = block.to_pandas().astype({k: "int64" for k in OD_KEYS})
            if frame.Car21.isna().any() or frame.Car21.lt(0).any():
                raise ValueError("Missing or negative original demand")
            frame = frame[frame.origin_node.ne(frame.destination_node)].assign(
                source_row=lambda x: np.arange(len(x)))
            for arm in sums:
                od = frame if arm == "control" else allocate(frame, shares[arm])
                sums[arm]["rows"] += len(od)
                sums[arm]["trips"] += float(od.Car21.sum())
                sums[arm]["trip_miles"] += miles_times_trips(od, coords)
                if arm in writers:
                    positive = od[od.Car21.gt(0)]
                    intended[arm].update(positive.origin_node)
                    intended[arm].update(positive.destination_node)
                    writers[arm].write_table(pa.Table.from_pandas(od, schema=schema, preserve_index=False))
    for arm, stat in sums.items():
        stat["haul_mi"] = stat.pop("trip_miles") / stat["trips"]
        np.testing.assert_allclose(stat["trips"], sums["control"]["trips"], rtol=1e-9, atol=0)
        if not .98 <= stat["haul_mi"] / sums["control"]["haul_mi"] <= 1.02:
            raise ValueError(f"{arm} outside matched ±2% haul window: {stat}")
    for arm, nodes in intended.items():
        pd.Series(sorted(nodes & set(keys.centroid_node)), name="centroid_node").to_csv(
            a.output / f"{arm}_intended.csv", index=False)
    for arm, frame in shares.items():
        frame.to_csv(a.output / f"{arm}_weights.csv", index=False)
    unmatched.to_csv(a.output / "retained_ct_road_nodes.csv", index=False)
    result = json.dumps(sums, indent=2)
    (a.output / "preflight.json").write_text(result + "\n")
    print(result)


if __name__ == "__main__":
    main()
