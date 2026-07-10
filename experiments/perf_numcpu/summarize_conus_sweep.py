#!/usr/bin/env python3
"""Summarize CONUS Pass B numcpu sweep runs into a markdown table."""

from __future__ import annotations

import json
from pathlib import Path

PERF_DIR = Path(__file__).resolve().parent
RUNS_ROOT = PERF_DIR / "runs"
OUT_PATH = PERF_DIR / "GOAL1_CONUS_SWEEP_SUMMARY.md"


def main() -> int:
    rows: list[dict] = []
    for meta_path in sorted(RUNS_ROOT.glob("goal1_conus_passb_cpu*_*/run_meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("mode") != "pass_b_conus_va_toy":
            continue
        parsed = meta.get("parsed_timing") or {}
        rows.append(
            {
                "num_cpu": meta.get("num_cpu"),
                "wall_sec": meta.get("wall_clock_sec"),
                "lcp_sec": parsed.get("lcp_pool_sec"),
                "stream_p1": parsed.get("streaming_pass1_sec"),
                "stream_p2": parsed.get("streaming_pass2_sec"),
                "path_rows": parsed.get("path_rows"),
                "origins": parsed.get("origins_total"),
                "run": meta_path.parent.name,
            }
        )

    rows.sort(key=lambda r: (r["num_cpu"] or 0))
    lines = [
        "# Goal 1 - CONUS Pass B numcpu sweep (VA toy raster / 50k OD)",
        "",
        "Track A stand-in: `inputs/test_141node_50m/va_hazard_*_{base,low,high}.tif` on full FAF5 network.",
        "",
        "| num_cpu | wall (s) | LCP (s) | stream p1 | stream p2 | path rows | origins | run |",
        "|---------|----------|---------|-----------|-----------|-----------|---------|-----|",
    ]
    for row in rows:
        lines.append(
            f"| {row['num_cpu']} | {row['wall_sec']} | {row.get('lcp_sec')} | "
            f"{row.get('stream_p1')} | {row.get('stream_p2')} | {row.get('path_rows')} | "
            f"{row.get('origins')} | `{row['run']}` |"
        )
    if not rows:
        lines.append("| _no runs yet_ | | | | | | | |")
    lines.extend(
        [
            "",
            "Generate: `python experiments/perf_numcpu/summarize_conus_sweep.py`",
        ]
    )
    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUT_PATH.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
