"""Reallocate selected Harvey-15 international legs to official port centroids."""
import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from prepare_faf_conus_subcounty_od import allocate, miles_times_trips
from prepare_faf_subcounty_od import OD_KEYS

PORTS = {61: (100174, 100178), 486: (100146,)}
MARKETS = ((2, "import", "dms_orig", "origin_node", "import_out"),
           (3, "export", "dms_dest", "destination_node", "export_in"))
GROUP = ["dms_orig", "dms_dest", "sctgG5", "trade_type"]


def load_regional(source):
    raw = pd.read_csv(source, usecols=[*GROUP[:2], "trade_type", "dms_mode", "sctg2", "tons_2022"])
    raw = raw[raw.dms_mode.eq(1) & ((raw.trade_type.eq(2) & raw.dms_orig.isin(PORTS)) |
                                   (raw.trade_type.eq(3) & raw.dms_dest.isin(PORTS)))].copy()
    raw["sctgG5"] = pd.cut(raw.sctg2, [0, 9, 14, 19, 33, 99],
                          labels=["sctg0109", "sctg1014", "sctg1519", "sctg2033", "sctg3499"])
    if raw.sctgG5.isna().any():
        raise ValueError("Unmapped commodity group")
    return raw.groupby(GROUP, observed=True, as_index=False).tons_2022.sum()


def factor(path, direction, counties):
    f = pd.read_csv(path).rename(columns={f"dms_{direction}_cnty": "county_fips"})
    node = "origin_node" if direction == "orig" else "destination_node"
    return f.merge(counties, on="county_fips", validate="many_to_one").rename(columns={"node_id": node})


def total(frame):
    return frame.groupby(OD_KEYS, sort=True).Car21.sum()


def endpoint_delta(cells, shares, endpoint, weights):
    county_pairs = cells.groupby(OD_KEYS, as_index=False).Car21.sum()
    withdrawn = allocate(county_pairs.assign(source_row=np.arange(len(county_pairs))), shares)
    outputs = []
    other = next(col for col in OD_KEYS if col != endpoint)
    leg = "in_share" if other == "destination_node" else "out_share"
    other_shares = shares.loc[shares[leg].gt(0), ["node_id", "centroid_node", leg]]
    allocated = county_pairs.merge(other_shares, left_on=other, right_on="node_id", validate="many_to_many")
    allocated[other] = allocated.centroid_node
    for node, portion in weights.items():
        row = allocated.assign(**{endpoint: int(node)}, Car21=allocated.Car21 * allocated[leg] * portion)
        outputs.append(row[[*OD_KEYS, "Car21"]])
    deposited = pd.concat(outputs, ignore_index=True)
    np.testing.assert_allclose(deposited.Car21.sum(), withdrawn.Car21.sum(), rtol=1e-9, atol=0)
    return withdrawn, deposited


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("faf_root", "inputs", "refs", "output"):
        parser.add_argument(name, type=Path)
    a = parser.parse_args()
    counties = pd.read_csv(a.inputs / "county_node_crosswalk_subset.csv")[["county_fips", "node_id"]]
    keys = pd.read_csv(a.inputs / "connector_crosswalk.csv")[["centroid_id", "centroid_node"]].drop_duplicates()
    directional = pd.read_csv(a.refs / "directional_centroid_totals.csv").merge(
        keys, on="centroid_id", validate="one_to_one").set_index("centroid_id")
    shares = pd.read_csv(a.refs / "weights_parent_mean.csv")
    baseline = pd.read_parquet(a.refs / "harvey15_cs_assignment_parent_mean.pq").astype(
        {col: "int64" for col in OD_KEYS})
    original = pd.read_parquet(a.inputs / "faf5_od_matrix_subset.pq").astype({col: "int64" for col in OD_KEYS})
    original = original[original.origin_node.ne(original.destination_node)]
    regional = load_regional(a.faf_root / "FAF5.7.1/FAF5.7.1.csv")
    factors = a.faf_root / "county_disaggregation_factors"
    origins = factor(factors / "truck_origin_factors.csv", "orig", counties)
    dests = factor(factors / "truck_destination_factors.csv", "dest", counties)
    additions, removals, county_removals, budgets, conservation = [], [], [], [], []
    for code, market, zone_key, endpoint, field in MARKETS:
        for zone, ports in PORTS.items():
            selected = regional[(regional.trade_type == code) & (regional[zone_key] == zone)]
            cells = selected.merge(origins, on=["dms_orig", "sctgG5"]).merge(
                dests, on=["dms_dest", "sctgG5"])
            cells = cells.loc[cells.origin_node.ne(cells.destination_node)].copy()
            cells["Car21"] = cells.tons_2022 * cells.f_orig * cells.f_dest * 1000 / (365 * 20)
            prior = cells.groupby(GROUP, observed=True).Car21.sum()
            available = prior.sum()
            observed = directional.loc[list(ports), [field, "centroid_node"]].set_index("centroid_node")[field]
            if available <= 0 or observed.isna().any() or observed.le(0).any():
                raise ValueError(f"Incomplete allocation evidence for {market} {zone}")
            fraction = min(1.0, observed.sum() / available)
            cells["Car21"] *= fraction
            moved = cells.groupby(GROUP, observed=True).Car21.sum()
            residual = prior * (1 - fraction)
            np.testing.assert_allclose(moved + residual, prior, rtol=1e-9, atol=0)
            check = pd.concat([prior.rename("base"), moved.rename("moved"), residual.rename("retained")], axis=1)
            conservation.append(check.reset_index())
            weights = observed / observed.sum()
            withdrawn, deposited = endpoint_delta(cells, shares, endpoint, weights)
            county_removals.append(cells[[*OD_KEYS, "Car21"]])
            removals.append(withdrawn)
            additions.append(deposited)
            for cid, node in directional.loc[list(ports), ["centroid_node"]].itertuples():
                budgets.append({"market": market, "faf_zone": zone, "centroid_id": int(cid),
                                "centroid_node": int(node), "available_zone_trips": float(available),
                                "published_target": float(observed.loc[node]),
                                "allocated_trips": float(moved.sum() * weights.loc[node]),
                                "zone_fraction": float(fraction)})
    old = total(original)
    removed_county = total(pd.concat(county_removals))
    if not removed_county.index.isin(old.index).all():
        raise ValueError("Reconstructed market OD includes a pair absent from the control")
    if (removed_county - old.loc[removed_county.index] > old.loc[removed_county.index] * 1e-9).any():
        raise ValueError("Reconstructed market OD exceeds the original county pair")
    old = total(baseline)
    removed = total(pd.concat(removals))
    if not removed.index.isin(old.index).all():
        raise ValueError("Withdrawal includes an endpoint pair absent from the C+S control")
    difference = old.sub(removed, fill_value=0)
    if difference.lt(-old * 1e-9).any():
        raise ValueError("Gateway withdrawal exceeds base demand")
    new = difference.clip(lower=0).add(total(pd.concat(additions)), fill_value=0)
    result = new[new.gt(0)].rename("Car21").reset_index()
    if result.origin_node.eq(result.destination_node).any():
        raise ValueError("Gateway pilot produced same-node trips")
    np.testing.assert_allclose(result.Car21.sum(), baseline.Car21.sum(), rtol=1e-9, atol=0)
    coords = pd.read_csv(a.refs / "centroid_coords.csv", index_col="node_id")
    base_haul = miles_times_trips(baseline, coords) / baseline.Car21.sum()
    pilot_haul = miles_times_trips(result, coords) / result.Car21.sum()
    if not .98 <= pilot_haul / base_haul <= 1.02:
        raise ValueError(f"Haul gate failed: {base_haul} vs {pilot_haul}")
    a.output.mkdir(parents=True, exist_ok=False)
    result.to_parquet(a.output / "harvey15_gateway_od.pq", index=False)
    pd.concat(conservation).to_csv(a.output / "conservation.csv", index=False)
    pd.DataFrame(budgets).to_csv(a.output / "gateway_budgets.csv", index=False)
    report = {"baseline_haul_mi": base_haul, "pilot_haul_mi": pilot_haul,
              "rows": len(result), "trips_day": float(result.Car21.sum()),
              "trips_moved_day": float(removed.sum()), "gateways": budgets}
    (a.output / "preflight.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
