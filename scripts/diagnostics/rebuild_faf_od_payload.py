#!/usr/bin/env python3
"""Rebuild the conterminous freight node OD from the by-commodity FAF5 matrix with a chosen payload basis.

Modes
  flat20  : keep Car21 as stored (flat 20 t/truck). Must reproduce faf5_od_matrix.pq and the conterminous file exactly.
  t29     : rescale each row by 20 / T29 payload of its sctgG5 (so trucks = daily_tons-implied trips at T29 payloads).

Chain reproduced: by_sctg -> sum Car21 by (origin_node, destination_node) -> drop AK/HI + remap (make_conterminous_od.transform_od).
Writes <out>/faf5_od_matrix_{mode}_node.pq, <out>/faf5_od_matrix_{mode}_conterminous.pq and <out>/report_{mode}.json.
"""
from __future__ import annotations
import argparse, json, sys
from pathlib import Path
import numpy as np, pandas as pd, pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from make_conterminous_od import transform_od  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["flat20", "t29"], required=True)
    ap.add_argument("--by-sctg", type=Path, required=True)
    ap.add_argument("--t29", type=Path, required=True)
    ap.add_argument("--remap-csv", type=Path, required=True)
    ap.add_argument("--crosswalk", type=Path, required=True, help="county_node_crosswalk_conus_single_node.csv (defines AK/HI drop nodes)")
    ap.add_argument("--reference-node", type=Path, help="faf5_od_matrix.pq to compare (flat20)")
    ap.add_argument("--reference-conterminous", type=Path, help="faf5_od_matrix_conterminous.pq to compare (flat20)")
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--commodity", help="optional sctgG5 group (e.g. sctg0109): keep only that group, for the commodity split")
    a = ap.parse_args()
    a.out_dir.mkdir(parents=True, exist_ok=True)

    df = pq.read_table(a.by_sctg, columns=["origin_node", "destination_node", "sctgG5", "Car21", "annual_tons"]).to_pandas()
    rep = {"mode": a.mode, "rows_in": int(len(df)), "car21_in": float(df.Car21.sum()), "annual_tons": float(df.annual_tons.sum())}
    t29 = pd.read_csv(a.t29, comment="#")
    pay = {str(k).lower().replace("sctg", ""): float(v) for k, v in zip(t29.sctgG5, t29.payload_tons) if k != "all"}
    keys = df.sctgG5.astype(str).str.lower().str.replace("sctg", "", regex=False)
    if a.commodity:
        keep = (keys == a.commodity.lower().replace("sctg", "")).to_numpy()
        df = df[keep].reset_index(drop=True); keys = keys[keep].reset_index(drop=True); rep["commodity"] = a.commodity
    rep["sctg_values"] = sorted(keys.unique().tolist()); rep["t29_payload"] = pay
    if set(rep["sctg_values"]) - set(pay):
        raise SystemExit(f"sctg without T29 payload: {set(rep['sctg_values']) - set(pay)}")
    # implied payload in stored Car21
    implied = (df.annual_tons / (df.Car21 * 365.0)).replace([np.inf], np.nan)
    rep["implied_stored_payload_by_sctg"] = {k: float(np.nanmedian(implied[keys == k])) for k in pay}
    if a.mode == "t29":
        scale = keys.map(lambda k: 20.0 / pay[k]).to_numpy()
        df["Car21"] = df.Car21.to_numpy() * scale
    rep["car21_after_scale"] = float(df.Car21.sum())
    node = df.groupby(["origin_node", "destination_node"], sort=True, as_index=False)["Car21"].sum()
    rep["node_rows"] = int(len(node)); rep["node_flow"] = float(node.Car21.sum())
    cw = pd.read_csv(a.crosswalk, dtype=str)
    drop_nodes = set(cw.loc[cw.state_fips.isin(["02", "15"]), "node_id"].astype("int64"))
    rm = pd.read_csv(a.remap_csv)
    remap = dict(zip(rm.old_node.astype("int64"), rm.new_node.astype("int64")))
    conus, st = transform_od(node, remap, drop_nodes)
    rep["transform"] = st; rep["conus_rows"] = int(len(conus)); rep["conus_flow"] = float(conus.Car21.sum())
    node.to_parquet(a.out_dir / f"faf5_od_matrix_{a.mode}_node.pq", index=False)
    conus.to_parquet(a.out_dir / f"faf5_od_matrix_{a.mode}_conterminous.pq", index=False)

    def cmp(ref: Path, new: pd.DataFrame, tag: str):
        r = pq.read_table(ref).to_pandas()
        m = r.merge(new, on=["origin_node", "destination_node"], how="outer", suffixes=("_ref", "_new"), indicator=True)
        both = m[m._merge == "both"]
        rep[f"compare_{tag}"] = {
            "ref_rows": int(len(r)), "new_rows": int(len(new)), "ref_only": int((m._merge == "left_only").sum()),
            "new_only": int((m._merge == "right_only").sum()), "ref_flow": float(r.Car21.sum()), "new_flow": float(new.Car21.sum()),
            "max_abs_diff": float((both.Car21_ref - both.Car21_new).abs().max()) if len(both) else None,
            "rel_flow_diff": float(new.Car21.sum() / r.Car21.sum() - 1)}
    if a.reference_node: cmp(a.reference_node, node, "node")
    if a.reference_conterminous: cmp(a.reference_conterminous, conus, "conterminous")
    (a.out_dir / f"report_{a.mode}.json").write_text(json.dumps(rep, indent=2))
    print(json.dumps(rep, indent=2))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
