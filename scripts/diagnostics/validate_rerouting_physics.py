#!/usr/bin/env python3
"""Validate Script 4 rerouting output for physical sanity, at any scale.

Checks the two things a correct rerouting solve must satisfy regardless of
network size -- these are the properties the freight/passenger shared-
capacity fix (2026-08) exists to guarantee, generalized here to every edge
in the network rather than one hand-picked toy edge:

1. Capacity: no open (non-damaged) edge's post-rerouting flow may exceed its
   real capacity. If both a freight and a passenger edge_flows file exist for
   the same scenario/day, their COMBINED flow is checked against capacity
   (this is the exact invariant the shared-capacity fix introduced -- before
   the fix, freight and passenger could each independently reach an edge's
   full capacity, silently double-booking it).
2. Conservation: flow removed from damaged edges (change_flow < 0, summed)
   must be accounted for by flow gained elsewhere (change_flow > 0, summed)
   plus flow reported isolated (unroutable) that same day -- nothing should
   vanish or appear from nowhere.

Usage
-----
    python scripts/diagnostics/validate_rerouting_physics.py <rerouting_dir> \
        [--out-dir <dir>] [--tolerance 1e-3] [--map]

<rerouting_dir> is a directory containing edge_flows_<mode>_s<scenario>_day
<day>.gpq and trip_isolations_<mode>_s<scenario>_day<day>.csv files, e.g.
results/rerouting_analysis/<variant>/<depth_key>/<event_key>/. Works
identically against a local toy run or a real Hopper CONUS output directory
(only reads the parquet/csv artifacts Script 4 already writes -- no config
or resiflow package import required).

Exits non-zero if any check fails, so this can gate a pipeline run.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import pandas as pd

EDGE_FLOWS_RE = re.compile(r"^edge_flows_(?P<mode>freight|passenger)_s(?P<scenario>[^_]+)_day(?P<day>\d+)\.gpq$")


def discover_runs(rerouting_dir: Path) -> dict[tuple[str, str], dict[str, Path]]:
    """Group edge_flows files by (scenario, day) -> {mode: path}."""
    runs: dict[tuple[str, str], dict[str, Path]] = {}
    for path in sorted(rerouting_dir.glob("edge_flows_*_s*_day*.gpq")):
        m = EDGE_FLOWS_RE.match(path.name)
        if not m:
            continue
        key = (m.group("scenario"), m.group("day"))
        runs.setdefault(key, {})[m.group("mode")] = path
    return runs


def isolation_flow_for(rerouting_dir: Path, mode: str, scenario: str, day: str) -> float:
    path = rerouting_dir / f"trip_isolations_{mode}_s{scenario}_day{day}.csv"
    if not path.exists():
        return 0.0
    df = pd.read_csv(path)
    if "Car21" not in df.columns or df.empty:
        return 0.0
    return float(pd.to_numeric(df["Car21"], errors="coerce").fillna(0.0).sum())


def check_capacity(gdf: pd.DataFrame, label: str, tolerance: float) -> list[dict]:
    """Flag any open edge whose flow exceeds its real capacity."""
    violations = []
    is_damaged = gdf.get("damage_level_max", pd.Series("no", index=gdf.index)).fillna("no") != "no"
    open_edges = gdf[~is_damaged & (gdf["acc_capacity"] > 0)]
    over = open_edges[open_edges["acc_flow"] > open_edges["acc_capacity"] * (1 + tolerance)]
    for _, row in over.iterrows():
        violations.append(
            {
                "check": "capacity",
                "label": label,
                "e_id": row["e_id"],
                "acc_flow": float(row["acc_flow"]),
                "acc_capacity": float(row["acc_capacity"]),
                "overage": float(row["acc_flow"] - row["acc_capacity"]),
            }
        )
    # NOTE: this is a DIFFERENT, pre-existing Script 4 finding, not the
    # freight/passenger capacity issue above -- confirmed (2026-08-29) to
    # reproduce identically on the unmodified freight-only default path, so
    # it is not something the shared-capacity fix introduced. It shows up on
    # an undamaged edge that carried baseline through-traffic for an OD whose
    # new post-disruption shortest path abandons that edge entirely (e.g. a
    # braess-style detour): road_links["acc_flow"] is pre-set to
    # current_flow - disrupted_flow before the incremental disrupted-only
    # network_flow_model solve, and if that solve's chosen paths never touch
    # this edge again, nothing ever overwrites it back to its real value --
    # it's left at that pre-solve placeholder, which can be negative. Worth a
    # separate investigation; flagged here rather than silently ignored.
    negative = open_edges[open_edges["acc_flow"] < -tolerance]
    for _, row in negative.iterrows():
        violations.append(
            {
                "check": "acc_flow_not_updated_by_solver",
                "label": label,
                "e_id": row["e_id"],
                "acc_flow": float(row["acc_flow"]),
            }
        )
    return violations


def check_conservation(gdf: pd.DataFrame, isolated_flow: float, label: str, tolerance: float, total_disrupted: float | None) -> dict:
    gain = float(gdf.loc[gdf["change_flow"] > 0, "change_flow"].sum())
    loss = float(gdf.loc[gdf["change_flow"] < 0, "change_flow"].sum())  # negative
    balance = gain + loss + isolated_flow
    abs_tol = max(1.0, abs(loss) * tolerance)
    result = {
        "label": label,
        "gain": gain,
        "loss": loss,
        "isolated_flow": isolated_flow,
        "balance": balance,
        "ok": abs(balance) <= abs_tol,
    }
    if total_disrupted is not None:
        result["total_disrupted_flow_reported"] = total_disrupted
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("rerouting_dir", type=Path)
    parser.add_argument("--out-dir", type=Path, default=None, help="Where to write the JSON report (default: rerouting_dir)")
    parser.add_argument("--tolerance", type=float, default=1e-3, help="Relative tolerance for capacity/conservation checks")
    parser.add_argument("--map", action="store_true", help="Also save a change_flow map PNG per (scenario, day)")
    args = parser.parse_args()

    rerouting_dir = args.rerouting_dir.resolve()
    if not rerouting_dir.is_dir():
        print(f"Not a directory: {rerouting_dir}", file=sys.stderr)
        return 2

    runs = discover_runs(rerouting_dir)
    if not runs:
        print(f"No edge_flows_*_s*_day*.gpq files found under {rerouting_dir}", file=sys.stderr)
        return 2

    import geopandas as gpd  # noqa: E402 -- only needed if files are found

    report: dict = {"rerouting_dir": str(rerouting_dir), "runs": []}
    any_failure = False

    for (scenario, day), mode_paths in sorted(runs.items()):
        loaded = {mode: gpd.read_parquet(path) for mode, path in mode_paths.items()}
        run_report: dict = {"scenario": scenario, "day": day, "modes": list(loaded), "violations": [], "conservation": []}

        # Per-mode checks (works even if only one mode was run).
        for mode, gdf in loaded.items():
            label = f"s{scenario}_day{day}_{mode}"
            iso_flow = isolation_flow_for(rerouting_dir, mode, scenario, day)
            run_report["violations"] += check_capacity(gdf, label, args.tolerance)
            run_report["conservation"].append(check_conservation(gdf, iso_flow, label, args.tolerance, None))

        # Combined check: only meaningful, and only possible, when both modes
        # were run for this scenario/day -- this is the exact invariant the
        # shared-capacity fix introduced (see module docstring).
        if "freight" in loaded and "passenger" in loaded:
            f_gdf, p_gdf = loaded["freight"], loaded["passenger"]
            combined = f_gdf[["e_id", "acc_capacity", "acc_flow", "damage_level_max"]].merge(
                p_gdf[["e_id", "acc_flow"]], on="e_id", suffixes=("_freight", "_passenger")
            )
            combined["acc_flow"] = combined["acc_flow_freight"] + combined["acc_flow_passenger"]
            label = f"s{scenario}_day{day}_combined"
            run_report["violations"] += check_capacity(combined, label, args.tolerance)
            combined_iso = isolation_flow_for(rerouting_dir, "freight", scenario, day) + isolation_flow_for(
                rerouting_dir, "passenger", scenario, day
            )
            f_change = f_gdf.set_index("e_id")["change_flow"]
            p_change = p_gdf.set_index("e_id")["change_flow"]
            combined_change = f_change.add(p_change, fill_value=0.0)
            combined_gdf = pd.DataFrame({"change_flow": combined_change})
            run_report["conservation"].append(
                check_conservation(combined_gdf, combined_iso, label, args.tolerance, None)
            )

        if run_report["violations"] or any(not c["ok"] for c in run_report["conservation"]):
            any_failure = True
        report["runs"].append(run_report)

        if args.map:
            try:
                import matplotlib.pyplot as plt
            except ImportError:
                print("matplotlib not available; skipping --map", file=sys.stderr)
            else:
                out_dir = args.out_dir or rerouting_dir
                out_dir.mkdir(parents=True, exist_ok=True)
                for mode, gdf in loaded.items():
                    fig, ax = plt.subplots(figsize=(10, 8))
                    plot_gdf = gdf.to_crs(4326) if gdf.crs is not None else gdf
                    vmax = float(plot_gdf["change_flow"].abs().max()) or 1.0
                    plot_gdf.plot(
                        ax=ax, column="change_flow", cmap="RdBu", vmin=-vmax, vmax=vmax, linewidth=1.2, legend=True
                    )
                    ax.set_title(f"Rerouting change in flow -- scenario {scenario}, day {day}, mode {mode}")
                    ax.set_axis_off()
                    fig.savefig(out_dir / f"change_flow_s{scenario}_day{day}_{mode}.png", dpi=150, bbox_inches="tight")
                    plt.close(fig)

    out_dir = args.out_dir or rerouting_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "rerouting_physics_report.json"
    report_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")

    for run in report["runs"]:
        status = "FAIL" if (run["violations"] or any(not c["ok"] for c in run["conservation"])) else "OK"
        print(f"[{status}] scenario={run['scenario']} day={run['day']} modes={run['modes']}")
        for c in run["conservation"]:
            flag = "OK" if c["ok"] else "MISMATCH"
            print(
                f"    conservation[{c['label']}]: gain={c['gain']:.2f} loss={c['loss']:.2f} "
                f"isolated={c['isolated_flow']:.2f} balance={c['balance']:.4f} [{flag}]"
            )
        for v in run["violations"][:10]:
            print(f"    violation: {v}")
        if len(run["violations"]) > 10:
            print(f"    ... and {len(run['violations']) - 10} more (see {report_path})")

    print(f"\nFull report: {report_path}")
    return 1 if any_failure else 0


if __name__ == "__main__":
    raise SystemExit(main())
