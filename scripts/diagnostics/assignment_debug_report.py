"""Visual debugging report for the ResiFlow cap-constrained assignment on a TNTP testbed.

Runs ``run_resiflow_capconstrained_from_testbed`` unchanged (wrappers only observe) and writes:

* ``iteration_table.csv``   one row per iteration (the ``ITER_AUDIT`` fields + old ``assigned_fraction``)
* ``od_delivery.csv``       demand, delivered flow and delivered share per zone pair
* ``trajectory.png``        delivered / structural / congestion / remaining demand vs iteration,
                            against the (misnamed) legacy ``assigned_fraction``
* ``od_matrix.png``         zone-to-zone delivered share, green = served, red = unserved, grey = no demand
* ``network_maps.png``      links by iteration of deletion (zone connectors dashed) and final volume/capacity
* ``deletions_by_iter.png`` small multiples of what was deleted at each iteration

Usage:  python scripts/diagnostics/assignment_debug_report.py anaheim --demand-scale 40 --out <dir>
Link geometry comes from the testbed's ``link_geojson`` when registered.
"""

from __future__ import annotations

import argparse
import dataclasses
import io
import logging
import re
from pathlib import Path

import duckdb
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.collections import LineCollection  # noqa: E402

import resiflow.assignment.compare as compare  # noqa: E402
import resiflow.road_revised as rr  # noqa: E402
from resiflow.networks.tntp import read_tntp_nodes  # noqa: E402
from resiflow.testbeds import load_testbed  # noqa: E402
from resiflow.networks.tntp import read_metadata  # noqa: E402


def run_observed(testbed_id: str, demand_scale: float | None, out: Path) -> dict:
    spec = load_testbed(testbed_id)
    if demand_scale is not None:
        spec = dataclasses.replace(spec, demand_scale=demand_scale)
    compare.load_testbed = lambda *_a, **_k: spec
    out.mkdir(parents=True, exist_ok=True)
    db_path = str(out / "assignment.duckdb")

    log_buf = io.StringIO()
    handler = logging.StreamHandler(log_buf)
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

    captured: dict = {"edges": [], "od": None, "links": None}
    orig_update, orig_flow = rr.update_network_structure, rr.network_flow_model

    def update_wrapper(n, network, temp_edge_flow, road_links, **kw):
        before = set(network.es["e_id"])
        flow = temp_edge_flow[["e_id", "flow"]].copy()
        result = orig_update(n, network, temp_edge_flow, road_links, **kw)
        flow["deleted"] = flow["e_id"].isin(before - set(network.es["e_id"]))
        flow["iteration"] = kw.get("iter_flag")
        captured["edges"].append(flow)
        return result

    def flow_wrapper(road_links, network, remain_od, *a, **kw):
        kw["db_path"] = db_path
        captured["od"] = remain_od[["origin_node", "destination_node", "Car21"]].copy()
        links, costs = orig_flow(road_links, network, remain_od, *a, **kw)
        captured["links"] = links.copy()
        return links, costs

    rr.update_network_structure, rr.network_flow_model = update_wrapper, flow_wrapper
    try:
        compare.run_resiflow_capconstrained_from_testbed(testbed_id)
    finally:
        rr.update_network_structure, rr.network_flow_model = orig_update, orig_flow
        logging.getLogger().removeHandler(handler)

    log = log_buf.getvalue()
    audits = pd.DataFrame(
        [dict(t.split("=") for t in ln.split()[1:]) for ln in log.splitlines() if ln.startswith("ITER_AUDIT")]
    ).apply(pd.to_numeric, errors="coerce")
    legacy = re.findall(r"Pass A convergence: remain_fraction=([0-9.]+) assigned_fraction=([0-9.]+) iteration=(\d+)", log)
    audits["legacy_assigned_fraction"] = [float(x[1]) for x in legacy][: len(audits)]
    con = duckdb.connect(db_path)
    delivered = con.execute(
        "SELECT origin, destination, SUM(flow) AS delivered FROM odpfc GROUP BY 1, 2"
    ).df()
    con.close()
    captured.update(spec=spec, audits=audits, delivered=delivered)
    return captured


def zone_set(spec) -> set[str]:
    meta = read_metadata(spec.net_path().read_text(encoding="utf-8").splitlines())
    return {str(i) for i in range(1, int(meta["NUMBER OF ZONES"]) + 1)}


def od_table(cap: dict) -> pd.DataFrame:
    od = cap["od"].rename(columns={"origin_node": "origin", "destination_node": "destination", "Car21": "demand"})
    od = od.astype({"origin": str, "destination": str})
    tab = od.merge(cap["delivered"].astype({"origin": str, "destination": str}), how="left", on=["origin", "destination"])
    tab["delivered"] = tab["delivered"].fillna(0.0)
    tab["share"] = tab["delivered"] / tab["demand"]
    return tab


def plot_trajectory(audits: pd.DataFrame, path: Path) -> None:
    it = audits["iteration"]
    fig, ax = plt.subplots(figsize=(8, 4.5))
    ax.stackplot(
        it,
        audits["delivered_frac_cum"],
        audits["isolated_structural_cum"] / (audits["delivered_cum"] / audits["delivered_frac_cum"]),
        audits["isolated_congestion_cum"] / (audits["delivered_cum"] / audits["delivered_frac_cum"]),
        audits["remain_frac"],
        labels=["delivered", "structurally isolated", "congestion isolated", "still remaining"],
        colors=["#2e7d32", "#9e9e9e", "#c62828", "#fbc02d"],
    )
    ax.plot(it, audits["legacy_assigned_fraction"], "k--", lw=2, label="legacy 'assigned_fraction' (includes isolated)")
    ax.set(xlabel="iteration", ylabel="share of initial demand", ylim=(0, 1.02), xlim=(it.min(), it.max()))
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=3, fontsize=8)
    ax.set_title("Where the demand went, by iteration")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def plot_od_matrix(tab: pd.DataFrame, zones: set[str], path: Path) -> None:
    order = sorted(zones, key=int)
    dem = tab.pivot_table(index="origin", columns="destination", values="demand", aggfunc="sum").reindex(index=order, columns=order)
    dlv = tab.pivot_table(index="origin", columns="destination", values="delivered", aggfunc="sum").reindex(index=order, columns=order)
    share = (dlv / dem).where(dem > 0)
    fig = plt.figure(figsize=(9.5, 9))
    gs = fig.add_gridspec(2, 3, width_ratios=[12, 1.6, 0.4], height_ratios=[1.6, 12], hspace=0.03, wspace=0.03)
    ax = fig.add_subplot(gs[1, 0])
    cmap = plt.get_cmap("RdYlGn").copy()
    cmap.set_bad("#e0e0e0")
    im = ax.imshow(np.ma.masked_invalid(share.values), cmap=cmap, vmin=0, vmax=1, aspect="auto")
    ax.set_xticks(range(len(order)), order, fontsize=6, rotation=90)
    ax.set_yticks(range(len(order)), order, fontsize=6)
    ax.set(xlabel="destination zone", ylabel="origin zone")
    top = fig.add_subplot(gs[0, 0], sharex=ax)
    top.bar(range(len(order)), dem.sum(axis=0).values, color="#607d8b")
    top.set_ylabel("demand", fontsize=7)
    top.tick_params(labelbottom=False, labelsize=6)
    right = fig.add_subplot(gs[1, 1], sharey=ax)
    right.barh(range(len(order)), dem.sum(axis=1).values, color="#607d8b")
    right.tick_params(labelleft=False, labelsize=6)
    fig.colorbar(im, cax=fig.add_subplot(gs[1, 2]), label="delivered share of demand")
    fig.suptitle("Zone-to-zone delivered share (grey = no demand; bars = zone demand totals)", fontsize=10)
    fig.savefig(path, dpi=150, bbox_inches="tight")
    plt.close(fig)


def _segments(links) -> list:
    return [np.asarray(g.coords) for g in links.geometry]


def plot_maps(cap: dict, zones: set[str], path_maps: Path, path_iters: Path) -> None:
    links = cap["links"].reset_index(drop=True)
    edges = pd.concat(cap["edges"], ignore_index=True)
    del_iter = edges[edges["deleted"]].set_index("e_id")["iteration"]
    links["del_iter"] = links["e_id"].map(del_iter)
    links["vc"] = links["acc_flow"] / links["current_capacity"].replace(0, np.nan)
    is_conn = links["from_id"].astype(str).isin(zones) | links["to_id"].astype(str).isin(zones)
    segs = _segments(links)
    nodes = read_tntp_nodes(cap["spec"].node_path())
    import geopandas as gpd

    pts = gpd.GeoDataFrame(
        nodes, geometry=gpd.points_from_xy(nodes["x"], nodes["y"]), crs=cap["spec"].source_crs
    ).to_crs(links.crs)
    pts = pts[pts["node"].astype(str).isin(zones)]
    def cut_zones(upto: float) -> set:
        """Zones whose every incident link was deleted at or before iteration ``upto``."""
        out = set()
        for z in zones:
            inc = links[(links["from_id"].astype(str) == z) | (links["to_id"].astype(str) == z)]
            if len(inc) and (inc["del_iter"] <= upto).all():
                out.add(z)
        return out

    def draw(ax, colors, lw, title, cut):
        lc = LineCollection(segs, colors=colors, linewidths=lw, linestyles=np.where(is_conn, "dotted", "solid"))
        ax.add_collection(lc)
        ax.scatter(pts.geometry.x, pts.geometry.y, s=18, marker="^", c=["red" if str(n) in cut else "black" for n in pts["node"]], zorder=3)
        ax.autoscale()
        ax.set_aspect("equal")
        ax.set_axis_off()
        ax.set_title(title, fontsize=9)

    fig, axes = plt.subplots(1, 2, figsize=(15, 7.5))
    n_it = int(links["del_iter"].max()) if links["del_iter"].notna().any() else 1
    cm = plt.get_cmap("viridis")
    col = [cm((d - 1) / max(n_it - 1, 1)) if pd.notna(d) else "#cfcfcf" for d in links["del_iter"]]
    draw(axes[0], col, np.where(links["del_iter"].notna(), 2.6, 0.6),
         "Iteration each link was deleted (grey = never)", cut_zones(float("inf")))
    sm = plt.cm.ScalarMappable(cmap=cm, norm=plt.Normalize(1, max(n_it, 2)))
    fig.colorbar(sm, ax=axes[0], shrink=0.6, label="iteration deleted")
    vc = links["vc"].clip(0, 1.0).fillna(0)
    cm2 = plt.get_cmap("YlOrRd")
    draw(axes[1], [cm2(v) for v in vc], 0.6 + 2.4 * vc, "Final accumulated flow / capacity", cut_zones(float("inf")))
    fig.suptitle("Dotted = zone connector; red triangle = zone with every incident link deleted", fontsize=9)
    sm2 = plt.cm.ScalarMappable(cmap=cm2, norm=plt.Normalize(0, 1))
    fig.colorbar(sm2, ax=axes[1], shrink=0.6, label="flow / capacity")
    fig.tight_layout()
    fig.savefig(path_maps, dpi=130)
    plt.close(fig)

    its = sorted(int(i) for i in del_iter.unique())[:12]
    if not its:
        return
    cols = min(4, len(its))
    rows = -(-len(its) // cols)
    fig, axs = plt.subplots(rows, cols, figsize=(4.2 * cols, 4 * rows), squeeze=False)
    aud = cap["audits"].set_index("iteration")
    for ax, k in zip(axs.ravel(), its):
        past = links["del_iter"] < k
        now = links["del_iter"] == k
        c = np.where(now, "#c62828", np.where(past, "#ff9800", "#cfcfcf"))
        draw(ax, c, np.where(now, 2.6, np.where(past, 1.2, 0.5)), "", cut_zones(k))
        ax.set_title(f"iter {k}: {int(now.sum())} deleted | delivered {aud.loc[k, 'delivered_frac_cum']:.1%}, remain {aud.loc[k, 'remain_frac']:.1%}", fontsize=8)
    for ax in axs.ravel()[len(its):]:
        ax.set_axis_off()
    fig.suptitle("Deleted this iteration (red), earlier (orange)", fontsize=10)
    fig.tight_layout()
    fig.savefig(path_iters, dpi=120)
    plt.close(fig)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("testbed")
    ap.add_argument("--demand-scale", type=float, default=None)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    cap = run_observed(args.testbed, args.demand_scale, args.out)
    zones = zone_set(cap["spec"])
    tab = od_table(cap)
    total, delivered = tab["demand"].sum(), tab["delivered"].sum()
    last = cap["audits"].iloc[-1]
    if abs(delivered - last["delivered_cum"]) > 1e-6 * total:
        logging.warning("odpfc delivered %.6g differs from ITER_AUDIT delivered_cum %.6g", delivered, last["delivered_cum"])
    cap["audits"].to_csv(args.out / "iteration_table.csv", index=False)
    tab.to_csv(args.out / "od_delivery.csv", index=False)
    plot_trajectory(cap["audits"], args.out / "trajectory.png")
    plot_od_matrix(tab, zones, args.out / "od_matrix.png")
    plot_maps(cap, zones, args.out / "network_maps.png", args.out / "deletions_by_iter.png")
    print(f"delivered {delivered / total:.4f} of demand over {len(cap['audits'])} iterations; wrote report to {args.out}")


if __name__ == "__main__":
    main()
