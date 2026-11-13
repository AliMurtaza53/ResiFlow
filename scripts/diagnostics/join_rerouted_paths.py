"""Join stage 4 OD path exports to the network: where did rerouted freight go?

Needs a stage 4 run with RESIFLOW_STAGE4_EXPORT_OD_PATHS=1, which writes for each recovery day
    odpfc_<mode>_s<scenario>_day<N>.pq            paths on the damaged network (disrupted OD pairs only)
    odpfc_<mode>_s<scenario>_day<N>_baseline.pq   paths of the same OD pairs on the intact network
Each row is one realised path: origin_node, destination_node, od_id, path (list of e_id), flow, per-flow cost columns.

Outputs under <results>/path_join/day<N>/:
    edge_flow_change.gpq   one row per edge touched by either path set: base_flow, post_flow, delta_flow, plus road class, bridge flag, geometry
    od_cost_change.csv     one row per OD pair: flow, baseline and post cost (operating + time + toll), delta
    summary.json           totals, share of flow whose path changed, top gaining and losing edges
Usage: python join_rerouted_paths.py --results <.../rerouting_analysis/<variant>/304/1> --base-edges <.../<variant>/edge_flows.gpq> --days 0 7
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb
import geopandas as gpd
import pandas as pd


def edge_flows(con, path: str) -> pd.DataFrame:
    return con.execute(
        f"SELECT e_id, SUM(flow) AS flow FROM (SELECT UNNEST(path) AS e_id, flow FROM read_parquet('{path}')) GROUP BY e_id"
    ).df()


def od_costs(con, path: str) -> pd.DataFrame:
    return con.execute(
        f"""SELECT origin_node, destination_node, SUM(flow) AS flow,
                   SUM(flow * (operating_cost_per_flow + time_cost_per_flow + toll_cost_per_flow)) AS cost,
                   COUNT(*) AS n_paths
            FROM read_parquet('{path}') GROUP BY origin_node, destination_node"""
    ).df()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--results", required=True, type=Path)
    ap.add_argument("--base-edges", required=True, type=Path, help="edge_flows.gpq with geometry (baseline run)")
    ap.add_argument("--days", nargs="+", type=int, default=[0])
    ap.add_argument("--mode", default="freight")
    ap.add_argument("--scenario", default="1")
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args()
    con = duckdb.connect()
    con.execute(f"PRAGMA threads={args.threads}")
    cols = ["e_id", "geometry", "length", "road_classification", "hpms_fclass", "road_bridge", "flood_depth_max"]
    edges = gpd.read_parquet(args.base_edges, columns=[c for c in cols if c != "flood_depth_max"])
    for day in args.days:
        stem = f"odpfc_{args.mode}_s{args.scenario}_day{day}"
        post, base = args.results / f"{stem}.pq", args.results / f"{stem}_baseline.pq"
        if not (post.exists() and base.exists()):
            print(f"day {day}: missing {post.name} or its baseline, skipped")
            continue
        out = args.results / "path_join" / f"day{day}"
        out.mkdir(parents=True, exist_ok=True)
        b, p = edge_flows(con, str(base)), edge_flows(con, str(post))
        m = b.merge(p, on="e_id", how="outer", suffixes=("_base", "_post")).fillna(0.0)
        m = m.rename(columns={"flow_base": "base_flow", "flow_post": "post_flow"})
        m["delta_flow"] = m.post_flow - m.base_flow
        g = gpd.GeoDataFrame(m.merge(edges, on="e_id", how="left"), geometry="geometry", crs=edges.crs)
        g.to_parquet(out / "edge_flow_change.gpq")
        ob, op = od_costs(con, str(base)), od_costs(con, str(post))
        o = ob.merge(op, on=["origin_node", "destination_node"], how="outer", suffixes=("_base", "_post")).fillna(0.0)
        o["delta_cost"] = o.cost_post - o.cost_base
        o["path_changed_share_proxy"] = (o.n_paths_post != o.n_paths_base).astype(int)
        o.to_csv(out / "od_cost_change.csv", index=False)
        top = lambda s, asc: m.sort_values("delta_flow", ascending=asc).head(10)[["e_id", "base_flow", "post_flow", "delta_flow"]].to_dict("records")  # noqa: E731
        summary = {
            "day": day, "od_pairs": int(len(o)), "flow_base": float(o.flow_base.sum()), "flow_post": float(o.flow_post.sum()),
            "cost_base": float(o.cost_base.sum()), "cost_post": float(o.cost_post.sum()), "delta_cost": float(o.delta_cost.sum()),
            "edges_gaining": int((m.delta_flow > 1e-9).sum()), "edges_losing": int((m.delta_flow < -1e-9).sum()),
            "top_gaining_edges": top(m, False), "top_losing_edges": top(m, True),
        }
        (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        print(f"day {day}: {summary['od_pairs']} OD pairs, delta cost {summary['delta_cost']:.0f}, "
              f"{summary['edges_gaining']} edges gain flow, {summary['edges_losing']} lose")


if __name__ == "__main__":
    main()
