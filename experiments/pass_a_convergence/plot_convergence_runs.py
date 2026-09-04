#!/usr/bin/env python3
"""Track and plot key convergence metrics across one or more Pass A runs.

Reads each run's parsed.json (produced by parse_assignment_log.py) and
overlays remain_fraction / progress_rel per iteration across runs, plus a
summary table of headline metrics (final remain_fraction, iteration count,
total isolated fraction, wall time if available from run_meta.json).

Usage:
    python plot_convergence_runs.py RUN_LABEL [RUN_LABEL ...]
    python plot_convergence_runs.py --all   # auto-discover every run with a parsed.json

Run labels are directory names under experiments/pass_a_convergence/runs/.
Output: notes/perf_findings/convergence_comparison_<timestamp>.png and a
matching .csv with the raw per-iteration data for all runs plotted.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_ROOT = Path(__file__).resolve().parent / "runs"
OUT_DIR = REPO_ROOT / "notes" / "perf_findings"


def load_run(run_dir: Path) -> tuple[pd.DataFrame, dict]:
    parsed_path = run_dir / "parsed.json"
    parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
    rows = parsed.get("iterations", [])
    df = pd.DataFrame(rows)
    df["run"] = run_dir.name
    meta_path = run_dir / "run_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
    summary = {
        "run": run_dir.name,
        "initial_supply": parsed.get("initial_supply"),
        "iteration_count": parsed.get("iteration_count"),
        "final_remain_fraction": (parsed.get("last_iteration") or {}).get("remain_fraction"),
        "total_isolated_fraction": parsed.get("total_isolated_fraction"),
        "stop_messages": "; ".join(parsed.get("stop_messages", [])) or (
            "killed / no stop reached" if parsed.get("log_truncated_no_stop") else ""
        ),
        "wall_sec": meta.get("wall_sec"),
    }
    return df, summary


def discover_all_runs() -> list[Path]:
    return sorted(
        p.parent for p in RUNS_ROOT.glob("*/parsed.json") if p.exists()
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_labels", nargs="*", help="Run directory names under experiments/pass_a_convergence/runs/")
    parser.add_argument("--all", action="store_true", help="Plot every run with a parsed.json")
    parser.add_argument("--label", default=None, help="Output file label (default: timestamp)")
    args = parser.parse_args()

    if args.all:
        run_dirs = discover_all_runs()
    else:
        if not args.run_labels:
            parser.error("Provide run labels or --all")
        run_dirs = [RUNS_ROOT / label for label in args.run_labels]

    missing = [d for d in run_dirs if not (d / "parsed.json").exists()]
    if missing:
        raise SystemExit(f"No parsed.json for: {[d.name for d in missing]}")

    all_iters = []
    summaries = []
    for run_dir in run_dirs:
        df, summary = load_run(run_dir)
        all_iters.append(df)
        summaries.append(summary)
    iters_df = pd.concat(all_iters, ignore_index=True)
    summary_df = pd.DataFrame(summaries)

    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5))
    for run_name, group in iters_df.groupby("run"):
        g = group.sort_values("iteration")
        axes[0].plot(g["iteration"], g["remain_fraction"], marker=".", label=run_name)
        if "progress_rel_pct" in g.columns:
            axes[1].semilogy(g["iteration"], g["progress_rel_pct"].clip(lower=1e-6), marker=".", label=run_name)

    axes[0].set_xlabel("iteration")
    axes[0].set_ylabel("remain_fraction")
    axes[0].set_title("Remaining unassigned demand by iteration")
    axes[0].legend(fontsize=8)
    axes[0].grid(alpha=0.3)

    axes[1].set_xlabel("iteration")
    axes[1].set_ylabel("progress_rel (%) [log scale]")
    axes[1].set_title("Per-iteration progress (log scale)")
    axes[1].legend(fontsize=8)
    axes[1].grid(alpha=0.3)

    fig.tight_layout()
    label = args.label or time.strftime("%Y%m%d_%H%M%S")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    png_path = OUT_DIR / f"convergence_comparison_{label}.png"
    csv_path = OUT_DIR / f"convergence_comparison_{label}.csv"
    fig.savefig(png_path, dpi=130)
    iters_df.to_csv(csv_path, index=False)

    print(f"Saved {png_path}")
    print(f"Saved {csv_path}")
    print("\nSummary:")
    print(summary_df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
