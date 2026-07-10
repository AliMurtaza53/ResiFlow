#!/usr/bin/env python3
"""Run Sioux Falls multihazard testbed (Pass A + all hazard scenarios).

Writes results under ``<output-root>/results`` with variant
``toy_sioux_falls_multihazard``. Re-run safe: unique scenario_param per hazard.

Example::

    python scripts/testbed/run_multihazard_sioux_falls.py

Writes to ``results/multihazard_panel/`` by default (outside pytest basetemp).
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"
VIZ_DIR = REPO_ROOT / "scripts" / "visualizations"
PYTHON = sys.executable
MULTIHAZARD_VARIANT = "toy_sioux_falls_multihazard"

MULTIHAZARD_CASES: tuple[tuple[str, str | None], ...] = (
    ("flood", "flood_surface"),
    ("flood", "flood_river"),
    ("flood", "flood_coastal"),
    ("earthquake", None),
    ("landslide", None),
    ("winter_storm", None),
)


def _run(cmd: list[str], *, env: dict[str, str], cwd: Path) -> None:
    print(">", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "results" / "multihazard_panel",
        help="Workspace root (config + results written here; default: results/multihazard_panel)",
    )
    parser.add_argument("--event", default="1", help="Hazard event id (default 1)")
    parser.add_argument(
        "--skip-pass-a",
        action="store_true",
        help="Skip Script 1 if baseline already exists",
    )
    parser.add_argument(
        "--summary-csv",
        type=Path,
        help="Optional path for multihazard summary CSV (default: <output-root>/multihazard_summary.csv)",
    )
    args = parser.parse_args()

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    run_pass_a = not args.skip_pass_a
    runner = f"""
import sys
from pathlib import Path
sys.path.insert(0, {str(TESTS_DIR)!r})
from multihazard_sioux_falls_fixtures import (
    MULTIHAZARD_VARIANT,
    build_multihazard_dataset,
    multihazard_env,
    scenario_for,
)
from toy_pipeline_fixtures import run_script

tmp = Path({str(output_root)!r})
config, _ = build_multihazard_dataset(tmp)
base_env = multihazard_env(tmp, config, hazard_type="flood", flood_subtype="flood_surface")
if {run_pass_a}:
    run_script("1_network_flow_model_revision.py", ["1", "1"], base_env)

cases = {list(MULTIHAZARD_CASES)!r}
event = {str(args.event)!r}
for hazard_type, flood_subtype in cases:
    env = multihazard_env(tmp, config, hazard_type=hazard_type, flood_subtype=flood_subtype)
    scenario = scenario_for(hazard_type, flood_subtype=flood_subtype, event_id=event)
    sp = str(scenario.scenario_param)
    run_script("2_intersection_analysis.py", [sp, event], env)
    run_script("3_damage_analysis.py", [], env)
    run_script("4_rerouting_and_recovery_scenario_loop.py", [sp, event, "1", "1"], env)
print("variant", {MULTIHAZARD_VARIANT!r})
print("results", tmp / "results")
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + str(REPO_ROOT)
    _run([PYTHON, "-c", runner], env=env, cwd=REPO_ROOT)

    if str(VIZ_DIR) not in sys.path:
        sys.path.insert(0, str(VIZ_DIR))
    from viz_data_loaders import build_multihazard_summary_table, validate_multihazard_summary

    results_root = output_root / "results"
    summary = build_multihazard_summary_table(
        results_root,
        MULTIHAZARD_VARIANT,
        event_key=int(args.event),
    )
    summary_path = args.summary_csv or (output_root / "multihazard_summary.csv")
    if not summary.empty:
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary.to_csv(summary_path, index=False)
        print(f"Wrote summary: {summary_path}")
    else:
        print("Warning: multihazard summary table is empty.", file=sys.stderr)
        return 1

    try:
        validate_multihazard_summary(summary, results_root=results_root, variant=MULTIHAZARD_VARIANT)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Results root: {results_root}")
    print(f"Set NIRD_RESULTS_ROOT={results_root}")
    print("Set NIRD_RESULTS_VARIANT=toy_sioux_falls_multihazard")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
