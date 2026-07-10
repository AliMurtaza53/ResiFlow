#!/usr/bin/env python3
"""Aggregate Goal 1 sweep runs into a markdown table."""

from __future__ import annotations

import json
from pathlib import Path

PERF_DIR = Path(__file__).resolve().parent
RUNS_ROOT = PERF_DIR / "runs"
OUT_PATH = PERF_DIR / "GOAL1_SWEEP_SUMMARY.md"


def main() -> int:
    rows: list[dict] = []
    for meta_path in sorted(RUNS_ROOT.glob("*/run_meta.json")):
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        if meta.get("mode") != "pass_a_sioux_falls":
            continue
        timing = meta.get("parsed_timing") or {}
        cpu = meta.get("cpu_samples") or {}
        rows.append(
            {
                "run": meta_path.parent.name,
                "num_cpu": meta.get("num_cpu"),
                "wall_sec": meta.get("wall_clock_sec"),
                "lcp_sec": timing.get("lcp_pool_sec"),
                "stream_p1": timing.get("streaming_pass1_sec"),
                "stream_p2": timing.get("streaming_pass2_sec"),
                "total_sim": timing.get("total_simulation_sec"),
                "cpu_frac": cpu.get("avg_cpu_fraction_of_machine"),
                "write_mb": (cpu.get("write_bytes_delta") or 0) / 1e6,
            }
        )

    lines = [
        "# Goal 1 — Sioux Falls Pass A numcpu sweep",
        "",
        "| num_cpu | wall (s) | LCP (s) | stream p1 | stream p2 | total sim | CPU frac | write (MB) | run |",
        "|---------|----------|---------|-----------|-----------|-----------|----------|------------|-----|",
    ]
    for row in sorted(rows, key=lambda r: (r["num_cpu"] or 0, r["run"])):
        lines.append(
            f"| {row['num_cpu']} | {row['wall_sec']} | {row['lcp_sec']} | "
            f"{row['stream_p1']} | {row['stream_p2']} | {row['total_sim']} | "
            f"{row['cpu_frac']} | {row['write_mb']:.2f} | `{row['run']}` |"
        )
    if not rows:
        lines.append("| (no runs yet) | | | | | | | | |")

    lines.extend(
        [
            "",
            "**Saturation note:** fill after review — compare `cpu_frac` vs `num_cpu` and whether",
            "`wall_sec` tracks `lcp_sec` or post-LCP streaming phases.",
        ]
    )
    OUT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(OUT_PATH.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
