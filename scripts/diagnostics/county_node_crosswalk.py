#!/usr/bin/env python3
"""County <-> network node crosswalk: build it, and check that a run's assignment OD can be rolled up to counties and states.

Why: ``network_flow_model`` sees OD rows as origin_node / destination_node only. A state-to-state (zone-pair) rollup needs every
node that appears in an OD row to map to exactly one county, and every county to have a state (state FIPS = first two digits of
the 5-digit county FIPS).

Two subcommands:

  build  Recover today's single-node county->node mapping from faf5_od_matrix_by_sctg.pq, which carries both county FIPS
         (origin_detail_zone / destination_detail_zone) and origin_node / destination_node. Same idea as
         scripts/extract_existing_county_crosswalk.py, but also checks one-to-one both ways and writes state FIPS.

  check  Take the node ids that actually appear in an assignment OD parquet (origin_node, destination_node) and join them to the
         crosswalk. PASS only if every node matches exactly one county and every county has a state. Exit code 1 on failure.

Node ids are coerced to integers then strings before any join (docs/CORRECTNESS_AND_PERFORMANCE_LESSONS.md, Lesson 1: one side
stored as '100169.0' and the other as '100169' silently matches nothing).

    python scripts/diagnostics/county_node_crosswalk.py build --od-by-sctg <faf5_od_matrix_by_sctg.pq> --out parameters/crosswalks/county_node_crosswalk_conus_single_node.csv
    python scripts/diagnostics/county_node_crosswalk.py check --od <faf5_od_matrix.pq> --crosswalk parameters/crosswalks/county_node_crosswalk_conus_single_node.csv
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
import pyarrow.parquet as pq


def norm_node(s: pd.Series) -> pd.Series:
    """Node id -> canonical string via int (handles int, float '100169.0', and str '100169')."""
    return pd.to_numeric(s, errors="raise").astype("int64").astype(str)


def norm_county(s: pd.Series) -> pd.Series:
    """County FIPS -> zero-padded 5-character string."""
    return pd.to_numeric(s, errors="raise").astype("int64").astype(str).str.zfill(5)


def build(od_by_sctg: Path, out: Path) -> int:
    cols = ["origin_detail_zone", "destination_detail_zone", "origin_node", "destination_node"]
    have = pq.ParquetFile(od_by_sctg).schema_arrow.names
    missing = [c for c in cols if c not in have]
    if missing:
        print(f"ERROR: {od_by_sctg} lacks columns {missing}; has {have}", file=sys.stderr)
        return 2
    df = pq.read_table(od_by_sctg, columns=cols).to_pandas()
    o = pd.DataFrame({"county_fips": norm_county(df.origin_detail_zone), "node_id": norm_node(df.origin_node)})
    d = pd.DataFrame({"county_fips": norm_county(df.destination_detail_zone), "node_id": norm_node(df.destination_node)})
    pairs = pd.concat([o, d], ignore_index=True).drop_duplicates()
    nodes_per_county = pairs.groupby("county_fips")["node_id"].nunique()
    counties_per_node = pairs.groupby("node_id")["county_fips"].nunique()
    print(f"distinct (county, node) pairs: {len(pairs):,} | counties: {pairs.county_fips.nunique():,} | nodes: {pairs.node_id.nunique():,}")
    print(f"counties with >1 node: {int((nodes_per_county > 1).sum())} | nodes serving >1 county: {int((counties_per_node > 1).sum())}")
    pairs["state_fips"] = pairs.county_fips.str[:2]
    states_per_node = pairs.groupby("node_id")["state_fips"].nunique()
    # A state rollup needs: every county has exactly one node, and every node sits in exactly one state.
    # A node shared by several counties of the SAME state (today: Connecticut planning regions 09120 and 09190) is fine for state
    # level but ambiguous for county level, so it is reported, not failed.
    ok = bool((nodes_per_county == 1).all() and (states_per_node == 1).all())
    shared = counties_per_node[counties_per_node > 1].index.tolist()
    if shared:
        print(f"WARNING county-level ambiguity: nodes shared by several counties: "
              f"{ {n: pairs[pairs.node_id == n].county_fips.tolist() for n in shared} }")
    out.parent.mkdir(parents=True, exist_ok=True)
    pairs.sort_values("county_fips")[["county_fips", "state_fips", "node_id"]].to_csv(out, index=False)
    print(f"wrote {out} ({len(pairs):,} rows); state-level rollup valid: {'YES' if ok else 'NO (see counts above)'}")
    return 0 if ok else 1


def check(od: Path, crosswalk: Path) -> int:
    cw = pd.read_csv(crosswalk, dtype=str)
    cw["node_id"] = norm_node(cw["node_id"])
    cw["county_fips"] = cw["county_fips"].str.zfill(5)
    t = pq.read_table(od, columns=["origin_node", "destination_node"]).to_pandas()
    nodes = pd.Series(pd.concat([norm_node(t.origin_node), norm_node(t.destination_node)]).unique(), name="node_id")
    m = nodes.to_frame().merge(cw, on="node_id", how="left")
    unmatched = m[m.county_fips.isna()]
    per_node_county = cw.groupby("node_id")["county_fips"].nunique()
    per_node_state = cw.groupby("node_id")["state_fips"].nunique()
    multi_county = per_node_county[per_node_county > 1]
    multi_state = per_node_state[per_node_state > 1]
    no_state = cw[cw.state_fips.isna() | (cw.state_fips.str.len() != 2)]
    print(f"OD nodes: {len(nodes):,} | matched to a county: {len(nodes) - len(unmatched):,} | unmatched: {len(unmatched):,}")
    print(f"nodes in >1 state: {len(multi_state):,} | counties without a 2-digit state: {len(no_state):,} | "
          f"nodes shared by >1 county (same state is OK for a state rollup): {len(multi_county):,}")
    print(f"states covered by OD nodes: {m.state_fips.nunique()} | counties covered: {m.county_fips.nunique():,}")
    if len(multi_county):
        print("county-level WARNING, shared nodes:", {n: cw[cw.node_id == n].county_fips.tolist() for n in multi_county.index[:10]})
    state_ok = unmatched.empty and multi_state.empty and no_state.empty
    if not unmatched.empty:
        print("sample unmatched nodes:", unmatched.node_id.head(10).tolist())
    print(f"STATE-LEVEL ROLLUP: {'PASS' if state_ok else 'FAIL'} | COUNTY-LEVEL ROLLUP: "
          f"{'PASS' if (state_ok and multi_county.empty) else 'AMBIGUOUS for ' + str(len(multi_county)) + ' node(s)'}")
    return 0 if state_ok else 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--od-by-sctg", type=Path, required=True)
    b.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("check")
    c.add_argument("--od", type=Path, required=True)
    c.add_argument("--crosswalk", type=Path, required=True)
    a = ap.parse_args()
    return build(a.od_by_sctg, a.out) if a.cmd == "build" else check(a.od, a.crosswalk)


if __name__ == "__main__":
    raise SystemExit(main())
