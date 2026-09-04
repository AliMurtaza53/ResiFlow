#!/usr/bin/env python3
"""Summarize Goal 6 profiling + benchmark results into one comparison figure.

Reads the hand-recorded numbers from GOAL6_TEST_RESULTS.md / this session's
pyinstrument runs (see notes/perf_findings/GOAL6_TEST_RESULTS.md) and renders
two panels:
  1. realize_paths_streaming time breakdown (before/after the cap_by_eid fix),
     as % of that function's own wall time (percentages are more robust to
     run-to-run noise than the raw seconds).
  2. Wall-clock comparison across the NumCpu x path-realization-strategy
     configs run today.
"""
from __future__ import annotations

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

RUNS_ROOT = __file__


def make_profile_breakdown_df() -> pd.DataFrame:
    # From pyinstrument text-renderer output, `--show-all`, 200k-OD/1-iter
    # CONUS-scale Pass A run (see scratch profiles referenced in
    # notes/perf_findings/GOAL6_TEST_RESULTS.md).
    rows = [
        ("before_fix", "python loop [self]", 48.749),
        ("before_fix", "dict.get", 21.250),
        ("before_fix", "gc.collect", 5.905),
        ("before_fix", "numpy math", 1.827 + 1.775 + 1.189 + 0.798 + 0.742),
        ("before_fix", "other", 87.147 - (48.749 + 21.250 + 5.905 + 1.827 + 1.775 + 1.189 + 0.798 + 0.742)),
        ("after_fix", "python loop [self]", 68.426),
        ("after_fix", "dict.get (remaining: event-edge match loop)", 28.817),
        ("after_fix", "gc.collect", 9.583),
        ("after_fix", "numpy math", 3.296 + 3.218 + 2.486 + 2.303 + 1.925 + 1.715 + 1.356),
        ("after_fix", "other", 125.751 - (68.426 + 28.817 + 9.583 + 3.296 + 3.218 + 2.486 + 2.303 + 1.925 + 1.715 + 1.356)),
    ]
    df = pd.DataFrame(rows, columns=["run", "category", "seconds"])
    totals = df.groupby("run")["seconds"].transform("sum")
    df["pct"] = 100 * df["seconds"] / totals
    return df


def make_wall_time_df() -> pd.DataFrame:
    rows = [
        ("streaming_arrays", 1, 329.7, "50k-OD/3-iter smoke (pre-strategy-cmp)"),
        ("streaming_arrays", 4, 320.6, "50k-OD/3-iter smoke (pre-strategy-cmp)"),
        ("streaming_arrays", 1, 591.1, "500k-OD/3-iter strategy cmp (noisier run)"),
        ("streaming_arrays", 4, 520.0, "500k-OD/3-iter strategy cmp (noisier run)"),
        ("duckdb_chunked_compact", 1, None, "BROKEN: od_id column bug"),
        ("duckdb_chunked_compact", 4, None, "BROKEN: od_id column bug"),
    ]
    return pd.DataFrame(rows, columns=["strategy", "num_cpu", "wall_sec", "note"])


def main() -> int:
    profile_df = make_profile_breakdown_df()
    wall_df = make_wall_time_df()

    fig, axes = plt.subplots(1, 2, figsize=(13, 5))

    pivot = profile_df.pivot(index="run", columns="category", values="pct").reindex(
        ["before_fix", "after_fix"]
    )
    pivot.plot(kind="bar", stacked=True, ax=axes[0], colormap="tab20")
    axes[0].set_title("realize_paths_streaming time breakdown (% of fn wall time)")
    axes[0].set_ylabel("% of function wall time")
    axes[0].legend(loc="upper left", bbox_to_anchor=(1.0, 1.0), fontsize=8)
    axes[0].set_xticklabels(axes[0].get_xticklabels(), rotation=0)

    plot_wall = wall_df.dropna(subset=["wall_sec"]).copy()
    plot_wall["label"] = plot_wall["strategy"] + " cpu=" + plot_wall["num_cpu"].astype(str)
    axes[1].bar(plot_wall["label"], plot_wall["wall_sec"], color="steelblue")
    axes[1].set_title("Pass A wall time by config (seconds)")
    axes[1].set_ylabel("wall time (s)")
    axes[1].tick_params(axis="x", rotation=30)

    fig.tight_layout()
    out_path = "notes/perf_findings/goal6_profile_summary.png"
    fig.savefig(out_path, dpi=130)
    print(f"Saved {out_path}")

    print("\nProfile breakdown (%):")
    print(pivot.round(1).to_string())
    print("\nWall time table:")
    print(wall_df.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
