#!/usr/bin/env python3
"""Post-hoc diagnostics for a completed (or in-progress) Pass A assignment
run: where the time goes, which physical edges chronically limit
assignment, and whether remaining demand is unassigned because no route
exists, because every route hit capacity, or because the run stopped
(iteration/time limit) before it could finish.

Deliberately NOT inline instrumentation inside network_flow_model()'s hot
loop -- reads the run's own log file and output parquets after the fact,
so it carries zero risk to the assignment engine itself. Every analysis
piece is optional and independent: pass whatever inputs you have (a run
without NIRD_LOG_RSS_CHECKPOINTS=1 / RESIFLOW_LOG_CAPACITY_BLOCKED_EDGES=1
set just won't have a timing/limiting-edges section -- it still reports
what it can from the rest).

Usage::

    python scripts/analyze_assignment_diagnostics.py \\
        --log-file logs_la_conn_BEFORE_2iter_2878530.out \\
        --isolated-od isolated_od.pq \\
        --original-od passenger_od_multinode_v3.pq \\
        --road-links faf5_road_links.gpq \\
        --county-crosswalk existing_county_to_node_crosswalk.csv \\
        --output-json diagnostics_report.json
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd

# "2026-10-23 14:17:17,132 2081157 1_network_flow_model_revision.py RSS checkpoint [iter1_start]: 12.34 GB"
_RSS_LINE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}).*?"
    r"RSS checkpoint \[(?P<label>\S+)\]: (?P<gb>[\d.]+) GB"
)
_CAPACITY_BLOCKED_LINE = re.compile(
    r"Capacity-blocked edge \[iter (?P<iter>\d+)\]: e_id=(?P<e_id>\S+) road=(?P<road>.*?) "
    r"tier=(?P<tier>\S+) lanes=(?P<lanes>\S+) "
    r"acc_capacity=(?P<acc_capacity>[\d.]+) current_capacity=(?P<current_capacity>[\d.]+)"
)


def parse_timing_checkpoints(log_text: str) -> pd.DataFrame:
    """RSS checkpoint log lines double as timing checkpoints -- every
    logging call is timestamped, so consecutive checkpoint labels bound a
    phase whose duration is just the timestamp delta. Returns one row per
    checkpoint with the elapsed time (seconds) since the PREVIOUS
    checkpoint, i.e. the cost of whatever ran between them.
    """
    rows = []
    for line in log_text.splitlines():
        m = _RSS_LINE.search(line)
        if m:
            ts = pd.to_datetime(m.group("ts"), format="%Y-%m-%d %H:%M:%S,%f")
            rows.append({"timestamp": ts, "label": m.group("label"), "rss_gb": float(m.group("gb"))})
    if not rows:
        return pd.DataFrame(columns=["label", "timestamp", "rss_gb", "elapsed_since_prev_s"])
    df = pd.DataFrame(rows).sort_values("timestamp").reset_index(drop=True)
    df["elapsed_since_prev_s"] = df["timestamp"].diff().dt.total_seconds()
    return df


def parse_capacity_blocked_edges(log_text: str) -> pd.DataFrame:
    """Aggregate capacity-blocked-edge log lines across all iterations:
    how many times each edge got dropped (chronic blocker vs one-off) and
    the demand it was carrying each time it did.
    """
    rows = []
    for line in log_text.splitlines():
        m = _CAPACITY_BLOCKED_LINE.search(line)
        if m:
            rows.append({
                "iteration": int(m.group("iter")), "e_id": m.group("e_id"),
                "road_name": m.group("road"), "tier": m.group("tier"),
                "lanes": m.group("lanes"), "acc_capacity": float(m.group("acc_capacity")),
                "current_capacity": float(m.group("current_capacity")),
            })
    if not rows:
        return pd.DataFrame(columns=["e_id", "road_name", "tier", "times_blocked", "total_acc_capacity"])
    df = pd.DataFrame(rows)
    agg = df.groupby(["e_id", "road_name", "tier"], as_index=False).agg(
        times_blocked=("iteration", "count"),
        total_acc_capacity=("acc_capacity", "sum"),
        max_acc_capacity=("acc_capacity", "max"),
    )
    return agg.sort_values("total_acc_capacity", ascending=False).reset_index(drop=True)


def classify_unassigned_demand(
    isolated_od: pd.DataFrame,
    road_links: "object",  # geopandas.GeoDataFrame, typed loosely to avoid a hard import at module load
) -> pd.DataFrame:
    """For each unassigned OD pair, is it genuinely unreachable (no path
    exists in the ORIGINAL, undamaged network at all -- a real network
    gap) or does a path exist but the pair still ended up unassigned (hit
    capacity on every available route, or the run stopped before it got
    there)? This script can only distinguish "structurally unreachable"
    from "reachable but unassigned" -- telling capacity-blocked apart from
    iteration/time-limit-reached for the "reachable" bucket requires
    knowing why the RUN stopped (see classify_run_stop_reason), which is a
    run-level fact, not a per-pair one.
    """
    import networkx as nx

    g = nx.Graph()
    g.add_edges_from(zip(road_links["from_id"], road_links["to_id"]))
    components = {node: i for i, comp in enumerate(nx.connected_components(g)) for node in comp}

    out = isolated_od.copy()
    out["origin_component"] = out["origin_node"].map(components)
    out["destination_component"] = out["destination_node"].map(components)
    out["reachable_in_original_network"] = (
        out["origin_component"].notna()
        & out["destination_component"].notna()
        & (out["origin_component"] == out["destination_component"])
    )
    out["classification"] = np.where(
        out["reachable_in_original_network"], "reachable_but_unassigned", "structurally_unreachable"
    )
    return out.drop(columns=["origin_component", "destination_component"])


def classify_run_stop_reason(log_text: str) -> str:
    """Why did the run actually stop: converged (total_remain reached 0),
    hit the iteration cap, or stagnated (insufficient progress N
    iterations running)? Distinguishes "capacity-blocked" from
    "iteration/time-limit-reached" for the reachable-but-unassigned bucket
    at the RUN level (both are "run stopped before finishing", but one
    means every iteration kept making progress and ran out of budget, the
    other means progress genuinely stalled against capacity).
    """
    if "Stop: Insufficient progress" in log_text:
        return "stagnated"
    if re.search(r"iter_flag >= max_iterations|iteration .* reached max", log_text):
        return "iteration_limit_reached"
    if "total_remain" in log_text and re.search(r"total_remain.{0,20}0\.0", log_text):
        return "converged"
    return "unknown"


def allocation_ratio_distribution(
    original_od: pd.DataFrame, isolated_od: pd.DataFrame, flow_col: str = "Car21"
) -> dict:
    """Per-OD-pair allocation ratio = 1 - (unassigned flow / original flow),
    i.e. what fraction of that pair's demand actually got assigned. Reports
    the FULL distribution (percentiles), not just the national mean -- a
    mean can look fine while hiding a large group of near-zero-allocation
    pairs stuck behind one oversubscribed edge.
    """
    orig = original_od.copy()
    orig["origin_node"] = orig["origin_node"].astype(str)
    orig["destination_node"] = orig["destination_node"].astype(str)
    iso = isolated_od.copy()
    iso["origin_node"] = iso["origin_node"].astype(str)
    iso["destination_node"] = iso["destination_node"].astype(str)

    merged = orig.merge(
        iso.rename(columns={"flow": "unassigned_flow"}),
        on=["origin_node", "destination_node"], how="left",
    )
    merged["unassigned_flow"] = merged["unassigned_flow"].fillna(0.0)
    merged = merged[merged[flow_col] > 0]
    merged["allocation_ratio"] = 1.0 - (merged["unassigned_flow"] / merged[flow_col])

    ratios = merged["allocation_ratio"].to_numpy()
    percentiles = [0, 1, 5, 10, 25, 50, 75, 90, 95, 99, 100]
    return {
        "n_pairs": int(len(ratios)),
        "mean": float(np.mean(ratios)) if len(ratios) else None,
        "percentiles": {f"p{p}": float(np.percentile(ratios, p)) for p in percentiles} if len(ratios) else {},
        "n_pairs_below_0.5_allocation": int((ratios < 0.5).sum()),
        "n_pairs_below_0.1_allocation": int((ratios < 0.1).sum()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--log-file", type=Path, default=None)
    parser.add_argument("--isolated-od", type=Path, default=None)
    parser.add_argument("--original-od", type=Path, default=None)
    parser.add_argument("--road-links", type=Path, default=None)
    parser.add_argument("--county-crosswalk", type=Path, default=None)
    parser.add_argument("--output-json", type=Path, default=None)
    args = parser.parse_args()

    report: dict = {}

    log_text = args.log_file.read_text(encoding="utf-8", errors="replace") if args.log_file else None
    if log_text is not None:
        timing = parse_timing_checkpoints(log_text)
        report["timing_checkpoints"] = (
            timing.to_dict(orient="records") if not timing.empty else "NIRD_LOG_RSS_CHECKPOINTS was not enabled for this run"
        )
        blocked = parse_capacity_blocked_edges(log_text)
        report["capacity_blocked_edges"] = (
            blocked.to_dict(orient="records") if not blocked.empty
            else "RESIFLOW_LOG_CAPACITY_BLOCKED_EDGES was not enabled for this run"
        )
        report["run_stop_reason"] = classify_run_stop_reason(log_text)
    else:
        report["timing_checkpoints"] = "no --log-file given"
        report["capacity_blocked_edges"] = "no --log-file given"
        report["run_stop_reason"] = "no --log-file given"

    isolated_od = pd.read_parquet(args.isolated_od) if args.isolated_od else None
    if isolated_od is not None and args.road_links is not None:
        import geopandas as gpd

        road_links = gpd.read_parquet(args.road_links)
        classified = classify_unassigned_demand(isolated_od, road_links)
        report["unassigned_demand_classification"] = (
            classified.groupby("classification")["flow"].agg(["count", "sum"]).reset_index().to_dict(orient="records")
        )
    else:
        report["unassigned_demand_classification"] = "need both --isolated-od and --road-links"

    if isolated_od is not None and args.original_od is not None:
        original_od = pd.read_parquet(args.original_od)
        report["allocation_ratio_distribution"] = allocation_ratio_distribution(original_od, isolated_od)
    else:
        report["allocation_ratio_distribution"] = "need both --isolated-od and --original-od"

    if isolated_od is not None and args.county_crosswalk is not None:
        crosswalk = pd.read_csv(args.county_crosswalk, dtype=str)
        node_to_county = crosswalk.set_index("node_id")["county_fips"] if "node_id" in crosswalk.columns else None
        if node_to_county is not None:
            iso = isolated_od.copy()
            iso["origin_node"] = iso["origin_node"].astype(str)
            iso["destination_county"] = iso["destination_node"].astype(str).map(node_to_county)
            report["unassigned_demand_by_destination_county"] = (
                iso.groupby("destination_county")["flow"].sum().sort_values(ascending=False).head(25).to_dict()
            )
        else:
            report["unassigned_demand_by_destination_county"] = "county crosswalk missing expected node_id column"
    else:
        report["unassigned_demand_by_destination_county"] = "need both --isolated-od and --county-crosswalk"

    print(json.dumps(report, indent=2, default=str))
    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        args.output_json.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"\nWrote {args.output_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
