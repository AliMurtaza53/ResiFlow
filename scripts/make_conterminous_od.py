#!/usr/bin/env python3
"""Re-snap the county OD nodes onto the current road network, and make the OD conterminous.

FINDING (2026-11-11, notes/perf_findings/OD_NODE_NUMBERING_MISMATCH.md): the OD files' node ids use a DIFFERENT NUMBERING from the
current road network's links. Against the older nodes file the OD nodes sit a median 1.7 km from their county centroids (99.8% within
25 km); against the links / Oct-23 nodes file they sit a median 1,386 km away, and only 2.9% of counties touch a link labelled with
their own state. The same 344,999 ids exist in both numberings, so the OD ran without error but every county's demand entered the
network at an unrelated place.

FIX. Each county's OD node has a TRUE location in the old (source) nodes file. For every distinct OD node:
  1. take its location in the source nodes file,
  2. snap to the nearest ELIGIBLE node of the current network: in the main connected component, and with no freeway-tier or ramp-class
     link (ramps are the saturating edges in the freight runs; they are poor attachment points), and not already used by another OD node,
  3. rewrite the OD node ids (a node shared by two counties, e.g. Connecticut planning regions, stays shared).
Alaska and Hawaii (state FIPS 02, 15) are dropped from the OD: the study is the conterminous US, and their nodes were scrambled too.
The road network itself is NOT edited. Dropped and remapped flow is reported; nothing is lost silently.

Everything uses projected-CRS KD-tree lookups (no per-row geometry work). Node ids go through int64 (Lesson 1) and OD dtypes are kept.

    python scripts/make_conterminous_od.py --links <links.gpq> --nodes <current nodes.gpq> --source-nodes <OD-numbering nodes.gpq> \
        --crosswalk parameters/crosswalks/county_node_crosswalk_conus_single_node.csv --centroids <faf5_centroid_nodes.gpq> \
        --od faf5_od_matrix.pq --od lodes_passenger_od_matrix.pq --out-dir <dir> \
        --remap-csv parameters/crosswalks/conus_od_node_remap.csv \
        --crosswalk-out parameters/crosswalks/county_node_crosswalk_conterminous.csv --report <report.json>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree

RAMP_CLASSES = {21, 22}  # faf5_class values for ramps / system ramps
MAX_SNAP_KM = 100.0  # fail loudly if a snap moves a node farther than this
FIPS_TO_ABBR = {"01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA",
                "15": "HI", "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD", "25": "MA",
                "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY",
                "37": "NC", "38": "ND", "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD", "47": "TN", "48": "TX",
                "49": "UT", "50": "VT", "51": "VA", "53": "WA", "54": "WV", "55": "WI", "56": "WY"}


def components(links: pd.DataFrame) -> tuple[pd.Series, int]:
    """Weakly connected component label per node (the model builds an undirected graph). Returns (labels indexed by node, main label)."""
    a = links["from_id"].astype("int64").to_numpy()
    b = links["to_id"].astype("int64").to_numpy()
    ids = np.unique(np.concatenate([a, b]))
    pos = pd.Series(np.arange(len(ids)), index=ids)
    ia, ib = pos.reindex(a).to_numpy(), pos.reindex(b).to_numpy()
    _, lab = connected_components(coo_matrix((np.ones(len(ia)), (ia, ib)), shape=(len(ids), len(ids))), directed=False)
    comp = pd.Series(lab, index=ids)
    return comp, int(comp.value_counts().index[0])


def eligible_nodes(links: pd.DataFrame, comp: pd.Series, main: int) -> pd.Index:
    """Main-component nodes with no freeway-tier or ramp-class link."""
    bad = links["assignment_tier"].astype(str).eq("freeway")
    if "faf5_class" in links.columns:
        bad |= pd.to_numeric(links["faf5_class"], errors="coerce").isin(RAMP_CLASSES)
    bad_nodes = set(links.loc[bad, "from_id"].astype("int64")) | set(links.loc[bad, "to_id"].astype("int64"))
    nodes = comp.index[comp.to_numpy() == main]
    return pd.Index([n for n in nodes if n not in bad_nodes])


def snap_nodes(src_xy: pd.DataFrame, cand_xy: pd.DataFrame, k: int = 16) -> pd.DataFrame:
    """For each source node (index old_node, columns x,y in metres) the nearest UNUSED candidate (index node_id, columns x,y).

    Deterministic: sources are processed in ascending id order. Returns old_node, new_node, distance_m."""
    tree = cKDTree(cand_xy[["x", "y"]].to_numpy())
    cand_ids = cand_xy.index.to_numpy()
    used: set[int] = set()
    rows = []
    kk = min(k, len(cand_ids))
    for old in sorted(src_xy.index):
        dist, idx = tree.query(src_xy.loc[old, ["x", "y"]].to_numpy(dtype=float), k=kk)
        for dd, ii in zip(np.atleast_1d(dist), np.atleast_1d(idx)):
            new = int(cand_ids[ii])
            if new not in used:
                used.add(new)
                rows.append({"old_node": int(old), "new_node": new, "distance_m": float(dd)})
                break
        else:
            raise RuntimeError(f"no unused eligible node within the {kk} nearest for source node {old}")
    return pd.DataFrame(rows)


def transform_od(df: pd.DataFrame, remap: dict[int, int], drop_nodes: set[int], flow_col: str = "Car21") -> tuple[pd.DataFrame, dict]:
    """Drop rows with an end in drop_nodes, then remap node ids. Preserves node column dtypes. Returns (new_df, stats)."""
    o = pd.to_numeric(df["origin_node"]).astype("int64")
    d = pd.to_numeric(df["destination_node"]).astype("int64")
    drop = o.isin(drop_nodes) | d.isin(drop_nodes)
    intra = o == d
    stats = {
        "rows_in": int(len(df)),
        "flow_in": float(df[flow_col].sum()),
        "flow_in_non_intrazonal": float(df.loc[~intra, flow_col].sum()),
        "rows_dropped": int(drop.sum()),
        "flow_dropped": float(df.loc[drop, flow_col].sum()),
        "flow_dropped_non_intrazonal": float(df.loc[drop & ~intra, flow_col].sum()),
    }
    keep = ~drop
    out = df.loc[keep].copy()
    o2 = o[keep].map(lambda v: remap.get(v, v)).astype("int64")
    d2 = d[keep].map(lambda v: remap.get(v, v)).astype("int64")
    out["origin_node"] = o2.astype(df["origin_node"].dtype) if df["origin_node"].dtype.kind in "iu" else o2.astype(str)
    out["destination_node"] = d2.astype(df["destination_node"].dtype) if df["destination_node"].dtype.kind in "iu" else d2.astype(str)
    stats["rows_out"] = int(len(out))
    stats["flow_out"] = float(out[flow_col].sum())
    stats["intrazonal_rows_in"] = int(intra.sum())
    stats["intrazonal_rows_out"] = int((o2 == d2).sum())
    return out.reset_index(drop=True), stats


def flow_between_components(df: pd.DataFrame, comp: pd.Series, flow_col: str = "Car21") -> float:
    o = pd.to_numeric(df["origin_node"]).astype("int64")
    d = pd.to_numeric(df["destination_node"]).astype("int64")
    return float(df.loc[(o != d) & (o.map(comp) != d.map(comp)), flow_col].sum())


def state_match_share(crosswalk: pd.DataFrame, links: pd.DataFrame) -> float:
    """Share of counties whose node touches at least one link labelled with the county's own state (chance level is about 3%)."""
    inc = pd.concat([pd.DataFrame({"node": links.from_id.astype("int64"), "S": links.STATE}),
                     pd.DataFrame({"node": links.to_id.astype("int64"), "S": links.STATE})])
    sets = inc.groupby("node").S.agg(lambda s: set(s.dropna()))
    ns = sets.reindex(crosswalk["node_id"].astype("int64")).to_numpy()
    abbr = crosswalk["state_fips"].map(FIPS_TO_ABBR).to_numpy()
    return float(np.mean([a in s if isinstance(s, set) else False for a, s in zip(abbr, ns)]))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--links", type=Path, required=True, help="current road links (from_id, to_id, STATE, assignment_tier, faf5_class)")
    ap.add_argument("--nodes", type=Path, required=True, help="current road nodes (the numbering the links use)")
    ap.add_argument("--source-nodes", type=Path, required=True, help="nodes file in the numbering the OD uses")
    ap.add_argument("--crosswalk", type=Path, required=True)
    ap.add_argument("--centroids", type=Path, help="county centroid points (CentroidID = county FIPS) for a distance sanity check")
    ap.add_argument("--od", type=Path, action="append", required=True)
    ap.add_argument("--out-dir", type=Path, required=True)
    ap.add_argument("--out-suffix", default="_conterminous")
    ap.add_argument("--drop-states", default="02,15")
    ap.add_argument("--remap-csv", type=Path, required=True)
    ap.add_argument("--crosswalk-out", type=Path, required=True)
    ap.add_argument("--report", type=Path, required=True)
    a = ap.parse_args()

    import geopandas as gpd

    cols = ["from_id", "to_id", "STATE", "assignment_tier", "faf5_class"]
    have = pq.ParquetFile(a.links).schema_arrow.names
    links = pq.read_table(a.links, columns=[c for c in cols if c in have]).to_pandas()
    comp, main_c = components(links)

    def load_xy(p: Path):
        g = gpd.read_parquet(p)
        g["node_id"] = g["node_id"].astype("int64")
        g = g.set_index("node_id")
        return pd.DataFrame({"x": g.geometry.x, "y": g.geometry.y}), g.crs

    cur_xy, cur_crs = load_xy(a.nodes)
    src_xy, src_crs = load_xy(a.source_nodes)
    if str(cur_crs) != str(src_crs):
        print(f"WARNING: node files have different CRS declarations ({cur_crs.to_string()[:25]} vs {src_crs.to_string()[:25]})", file=sys.stderr)

    cw = pd.read_csv(a.crosswalk, dtype=str)
    cw["nid"] = cw["node_id"].astype("int64")
    drop_states = set(a.drop_states.split(",")) if a.drop_states else set()
    is_drop = cw.state_fips.isin(drop_states)
    drop_nodes = set(cw.loc[is_drop, "nid"])
    keep_cw = cw[~is_drop].copy()
    old_nodes = sorted(set(keep_cw.nid))
    print(f"counties dropped ({a.drop_states}): {int(is_drop.sum())} | counties kept: {len(keep_cw):,} | distinct OD nodes to snap: {len(old_nodes):,}")

    cand = eligible_nodes(links, comp, main_c)
    cand_xy = cur_xy.reindex(cand)
    print(f"eligible target nodes (main component, no freeway/ramp link): {len(cand):,} of {len(cur_xy):,}")
    snap = snap_nodes(src_xy.reindex(old_nodes), cand_xy)
    snap["distance_km"] = (snap.distance_m / 1000).round(3)
    print(f"snap distance (old location -> new node), km: median {snap.distance_km.median():.3f}, p90 {snap.distance_km.quantile(.9):.3f}, "
          f"p99 {snap.distance_km.quantile(.99):.3f}, max {snap.distance_km.max():.2f}")
    if snap.distance_km.max() > MAX_SNAP_KM:
        print(snap.sort_values("distance_km", ascending=False).head(10).to_string(index=False), file=sys.stderr)
        print(f"ERROR: a snap moved a node farther than {MAX_SNAP_KM} km", file=sys.stderr)
        return 2

    remap = dict(zip(snap.old_node, snap.new_node))
    new_cw = keep_cw.copy()
    new_cw["node_id"] = new_cw["nid"].map(remap).astype(str)

    before = state_match_share(keep_cw.assign(node_id=keep_cw.nid.astype(str)), links)
    after = state_match_share(new_cw, links)
    print(f"counties whose node touches a link of their own state: BEFORE {before:.1%} -> AFTER {after:.1%}")
    report = {"drop_states": sorted(drop_states), "counties_kept": int(len(keep_cw)), "nodes_snapped": int(len(snap)),
              "snap_km_median": float(snap.distance_km.median()), "snap_km_max": float(snap.distance_km.max()),
              "state_match_before": before, "state_match_after": after, "od_files": {}}

    if a.centroids:
        cen = gpd.read_parquet(a.centroids).to_crs(cur_crs)
        cen["fi"] = cen["CentroidID"].astype("int64")
        cen = cen[cen.fi <= 56999].drop_duplicates("fi").set_index("fi")
        k2 = new_cw.assign(fi=new_cw.county_fips.astype(int))
        k2 = k2[k2.fi.isin(cen.index)]
        cp = cen.geometry.reindex(k2.fi)
        npnt = cur_xy.reindex(k2.node_id.astype("int64"))
        dkm = np.hypot(cp.x.to_numpy() - npnt.x.to_numpy(), cp.y.to_numpy() - npnt.y.to_numpy()) / 1000
        report["centroid_km_median_after"] = float(np.median(dkm))
        report["centroid_km_p99_after"] = float(np.quantile(dkm, 0.99))
        print(f"new node vs county centroid ({len(k2):,} counties), km: median {np.median(dkm):.1f}, p99 {np.quantile(dkm, 0.99):.1f}")

    a.out_dir.mkdir(parents=True, exist_ok=True)
    ok = after > 0.9
    for od_path in a.od:
        df = pq.read_table(od_path).to_pandas()
        new, st = transform_od(df, remap, drop_nodes)
        st["flow_between_components_before"] = flow_between_components(df, comp)
        st["flow_between_components_after"] = flow_between_components(new, comp)
        st["conservation_residual"] = st["flow_in"] - st["flow_out"] - st["flow_dropped"]
        out_path = a.out_dir / f"{od_path.stem}{a.out_suffix}.pq"
        pq.write_table(pa.Table.from_pandas(new, preserve_index=False), out_path)
        report["od_files"][od_path.name] = {**st, "output": str(out_path)}
        good = abs(st["conservation_residual"]) < 1e-6 * max(st["flow_in"], 1.0) and st["flow_between_components_after"] == 0.0
        ok &= good
        print(f"{od_path.name}: rows {st['rows_in']:,} -> {st['rows_out']:,}; flow {st['flow_in']:,.3f} -> {st['flow_out']:,.3f} "
              f"(dropped AK/HI {st['flow_dropped']:,.3f}); intrazonal rows {st['intrazonal_rows_in']:,} -> {st['intrazonal_rows_out']:,}; "
              f"between-component flow {st['flow_between_components_before']:,.3f} -> {st['flow_between_components_after']:,.3f}; "
              f"conservation residual {st['conservation_residual']:.2e} {'OK' if good else 'FAIL'}")

    a.crosswalk_out.parent.mkdir(parents=True, exist_ok=True)
    new_cw[["county_fips", "state_fips", "node_id"]].sort_values("county_fips").to_csv(a.crosswalk_out, index=False)
    snap[["old_node", "new_node", "distance_km"]].to_csv(a.remap_csv, index=False)
    a.report.write_text(json.dumps(report, indent=2))
    print(f"wrote {a.crosswalk_out} ({len(new_cw):,} counties), {a.remap_csv} ({len(snap):,} nodes), {a.report}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
