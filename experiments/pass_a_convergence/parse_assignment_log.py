#!/usr/bin/env python3
"""Parse Pass A Script 1 assignment log for convergence diagnostics."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

INITIAL_SUPPLY_RE = re.compile(r"The initial supply is\s+([0-9.eE+-]+)")
ITER_START_RE = re.compile(r"No\.(\d+) iteration starts:")
REMAIN_RE = re.compile(
    r"The total remain flow\s*\(after adjustment\) is:\s*([0-9.eE+-]+)\."
)
PROGRESS_RE = re.compile(
    r"assigned_delta=([0-9.eE+-]+),\s*progress_rel=([0-9.eE+-]+)%"
    r",\s*stagnant_iterations=(\d+)/(\d+)"
)
STOP_RE = re.compile(r"Stop: (.+)")
ISOLATION_RE = re.compile(r"with\s+([0-9.eE+-]+)\s+extra isolated flows")
INITIAL_ISOLATED_RE = re.compile(r"Initial isolated flows:\s*([0-9.eE+-]+)")
NON_ALLOCATED_RE = re.compile(r"Non_allocated_flow:\s*([0-9.eE+-]+)")
CONTROLS_RE = re.compile(
    r"max_iterations=([^,]+),\s*min_progress_rel=([^,]+),\s*stagnant_limit=(\d+)"
)


def parse_log(text: str) -> dict:
    initial_supply = None
    m = INITIAL_SUPPLY_RE.search(text)
    if m:
        initial_supply = float(m.group(1))

    controls = {}
    cm = CONTROLS_RE.search(text)
    if cm:
        controls = {
            "max_iterations": cm.group(1).strip(),
            "min_progress_rel": float(cm.group(2)),
            "stagnant_limit": int(cm.group(3)),
        }

    iterations: list[dict] = []
    per_iter_isolation: dict[int, dict] = {}
    current_iter: int | None = None
    for line in text.splitlines():
        sm = ITER_START_RE.search(line)
        if sm:
            current_iter = int(sm.group(1))
            continue
        if current_iter is None:
            continue
        iim = INITIAL_ISOLATED_RE.search(line)
        if iim:
            per_iter_isolation.setdefault(current_iter, {})["initial_isolated"] = float(
                iim.group(1)
            )
            continue
        nam = NON_ALLOCATED_RE.search(line)
        if nam:
            per_iter_isolation.setdefault(current_iter, {})["non_allocated"] = float(
                nam.group(1)
            )
            continue
        rm = REMAIN_RE.search(line)
        if rm:
            remain = float(rm.group(1))
            row: dict = {
                "iteration": current_iter,
                "total_remain": remain,
            }
            if initial_supply and initial_supply > 0:
                row["remain_fraction"] = remain / initial_supply
                row["assigned_fraction"] = 1.0 - row["remain_fraction"]
            iterations.append(row)
            continue
        pm = PROGRESS_RE.search(line)
        if pm and iterations and iterations[-1].get("iteration") == current_iter:
            iterations[-1].update(
                {
                    "assigned_delta": float(pm.group(1)),
                    "progress_rel_pct": float(pm.group(2)),
                    "stagnant_iterations": int(pm.group(3)),
                    "stagnant_limit": int(pm.group(4)),
                }
            )
            current_iter = None
            continue
        sm2 = ITER_START_RE.search(line)
        if sm2 and iterations and current_iter is not None:
            current_iter = None

    # merge per-iteration isolation channels ("Initial isolated flows" for
    # unreachable-node OD pairs, "Non_allocated_flow" for no-path-found OD
    # pairs) into their iteration rows.
    for row in iterations:
        iso = per_iter_isolation.get(row["iteration"], {})
        row["initial_isolated_flow"] = iso.get("initial_isolated", 0.0)
        row["non_allocated_flow"] = iso.get("non_allocated", 0.0)

    stops = [m.group(1) for m in STOP_RE.finditer(text)]
    truncated = not stops and bool(iterations)

    isolated_flow_at_stop = None
    isolated_fraction_at_stop = None
    for stop_msg in stops:
        im = ISOLATION_RE.search(stop_msg)
        if im:
            isolated_flow_at_stop = float(im.group(1))
            break
    if isolated_flow_at_stop is not None and initial_supply and initial_supply > 0:
        isolated_fraction_at_stop = isolated_flow_at_stop / initial_supply

    # Total isolated flow = per-iteration unreachable-node + no-path-found
    # isolation accumulated across every iteration, plus the final
    # "extra isolated flows" dump of whatever's left in remain_od at stop.
    # This should reconcile with SUM(flow) FROM isolated_od in the run's
    # DuckDB output (verified against a live run on 2026-07-13; see
    # notes/perf_findings/GOAL6_TEST_RESULTS.md).
    total_initial_isolated = sum(
        row["initial_isolated_flow"] for row in iterations
    )
    total_non_allocated = sum(row["non_allocated_flow"] for row in iterations)
    total_isolated_flow = total_initial_isolated + total_non_allocated + (
        isolated_flow_at_stop or 0.0
    )
    total_isolated_fraction = None
    if initial_supply and initial_supply > 0:
        total_isolated_fraction = total_isolated_flow / initial_supply

    return {
        "initial_supply": initial_supply,
        "controls": controls,
        "iterations": iterations,
        "iteration_count": len(iterations),
        "last_iteration": iterations[-1] if iterations else None,
        "stop_messages": stops,
        "log_truncated_no_stop": truncated,
        "isolated_flow_at_stop": isolated_flow_at_stop,
        "isolated_fraction_at_stop": isolated_fraction_at_stop,
        "total_initial_isolated_flow": total_initial_isolated,
        "total_non_allocated_flow": total_non_allocated,
        "total_isolated_flow": total_isolated_flow,
        "total_isolated_fraction": total_isolated_fraction,
    }


def normalize_log_text(text: str) -> str:
    """Join UTF-16 / wrapped log lines so iteration metrics parse reliably."""
    # Drop NUL padding common in UTF-16 decoded as latin1-ish artifacts
    text = text.replace("\x00", "")
    # Join continuation lines (no leading timestamp) onto previous line
    merged: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if merged and not re.match(r"^\d{4}-\d{2}-\d{2}", line.strip()):
            merged[-1] = merged[-1] + " " + line.strip()
        else:
            merged.append(line.strip())
    return "\n".join(merged)


def read_log(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        text = raw.decode("utf-16", errors="replace")
    elif raw.startswith(b"\xef\xbb\xbf"):
        text = raw.decode("utf-8-sig", errors="replace")
    else:
        text = raw.decode("utf-8", errors="replace")
    return normalize_log_text(text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_path", type=Path)
    parser.add_argument("--json-out", type=Path, default=None)
    parser.add_argument("--csv-out", type=Path, default=None)
    args = parser.parse_args()

    parsed = parse_log(read_log(args.log_path))
    print(json.dumps(parsed, indent=2))

    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(json.dumps(parsed, indent=2), encoding="utf-8")

    if args.csv_out and parsed["iterations"]:
        import csv

        args.csv_out.parent.mkdir(parents=True, exist_ok=True)
        fields = sorted({k for row in parsed["iterations"] for k in row.keys()})
        with args.csv_out.open("w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields)
            writer.writeheader()
            writer.writerows(parsed["iterations"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
