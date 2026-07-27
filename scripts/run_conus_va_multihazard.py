#!/usr/bin/env python3
"""Orchestrate the real VA multi-hazard comparison against a CONUS baseline.

Unlike scripts/testbed/run_multihazard_sioux_falls.py (synthetic toy network,
builds its own workspace), this points at a completed CONUS Pass A baseline
(edge_flows.gpq / baseline.duckdb under
<soge_clusters parent>/results/base_scenario/<results-variant>/) -- see
experiments/pass_a_convergence/hopper/submit_cpu8_convergence.slurm. This
script does NOT run Pass A; it runs the per-hazard disruption/damage/
rerouting sequence, per docs/PIPELINE_OVERVIEW.md's documented CONUS flow:

    Script 2 (disruption) -> Script 3 + 3_postprocess (direct damage) ->
    export_event_damaged_edges -> Pass B (Script 1, event_candidates mode,
    cheap -- only re-solves ODs whose paths cross damaged edges) -> Script 4
    (indirect/rerouting cost, combines with direct)

Every step -- reading the Pass A baseline AND writing this run's own
disruption/damage/rerouting outputs -- uses the SAME --results-variant.
This mirrors scripts/testbed/run_multihazard_sioux_falls.py's proven
single-variant pattern (see MULTIHAZARD_VARIANT there): the pipeline's
get_results_variant() resolves one variant name for both purposes, so there
is no separate "baseline" vs. "this run" variant to plumb -- an earlier
version of this script tried to split them via a
NIRD_BASE_SCENARIO_OUT_DIR override that pipeline.py's base-scenario loader
never actually reads, which silently broke Script 2's base-scenario load.
Different hazard events are told apart by scenario_param/event_id within
that one variant's folder, exactly like the toy testbed's summary table.

Hazard events are read from --hazards-manifest (schema: parameters/
hazards.va_real.example.json) rather than hardcoded, so adding/changing a
hazard is a config edit, not a code change -- this is "the one command to
regenerate everything" from docs/VA_MULTIHAZARD_COMPARISON.md.

Example::

    python scripts/run_conus_va_multihazard.py \
        --hazards-manifest /scratch/.../hazards.json \
        --results-variant convergence_cpu8
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))
VIZ_DIR = REPO_ROOT / "scripts" / "visualizations"
PYTHON = sys.executable

from resiflow.utils import load_config  # noqa: E402 (after sys.path setup above)


def run_script(name: str, args: list, env: dict) -> None:
    cmd = [PYTHON, str(REPO_ROOT / "scripts" / name), *map(str, args)]
    print(">", " ".join(cmd))
    subprocess.run(cmd, cwd=REPO_ROOT, env=env, check=True)


def load_events(manifest_path: Path) -> list[dict]:
    data = json.loads(manifest_path.read_text())
    events = data.get("events", [])
    if not events:
        raise SystemExit(f"No events found in {manifest_path}")
    return events


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hazards-manifest", type=Path, required=True)
    parser.add_argument(
        "--results-variant",
        required=True,
        help="Results variant that already holds the completed CONUS Pass A "
        "baseline (edge_flows.gpq/baseline.duckdb) -- this run's own "
        "disruption/damage/rerouting outputs are written into the same "
        "variant, differentiated by scenario_param/event_id.",
    )
    parser.add_argument("--num-chunks", type=int, default=20)
    parser.add_argument("--num-cpu", type=int, default=8)
    parser.add_argument("--summary-csv", type=Path, default=None)
    args = parser.parse_args()

    events = load_events(args.hazards_manifest)
    soge_clusters = Path(load_config(os.environ.get("RESIFLOW_CONFIG_PATH"))["paths"]["soge_clusters"])
    results_root = soge_clusters.parent / "results"

    base_env = os.environ.copy()
    base_env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + str(REPO_ROOT)
    base_env["RESIFLOW_HAZARDS_MANIFEST"] = str(args.hazards_manifest.resolve())
    base_env["RESIFLOW_RESULTS_VARIANT"] = args.results_variant
    base_env["NIRD_RESULTS_VARIANT"] = args.results_variant
    base_env["NIRD_BASE_SCENARIO_OUT_DIR"] = str(
        results_root / "base_scenario" / args.results_variant
    )

    for event in events:
        env = base_env.copy()
        hazard_type = str(event["hazard_type"]).strip().lower()
        subtype = event.get("hazard_subtype") or event.get("flood_subtype")
        scenario_param = int(event["scenario_param"])
        event_id = str(event.get("event_id", "1"))

        if hazard_type == "flood":
            env.pop("RESIFLOW_HAZARD_TYPE", None)
            if subtype:
                env["RESIFLOW_FLOOD_SUBTYPE"] = subtype
            else:
                env.pop("RESIFLOW_FLOOD_SUBTYPE", None)
        else:
            env["RESIFLOW_HAZARD_TYPE"] = hazard_type
            env.pop("RESIFLOW_FLOOD_SUBTYPE", None)
        env["RESIFLOW_SCENARIO_PARAM"] = str(scenario_param)

        print(f"\n=== {hazard_type} (subtype={subtype}) scenario_param={scenario_param} event={event_id} ===")

        run_script("2_intersection_analysis.py", [scenario_param, event_id], env)
        run_script("3_damage_analysis.py", [], env)
        run_script("3_postprocess_damage.py", [], env)

        # tables/ lives under soge_clusters; export_event_damaged_edges.py
        # resolves that root itself via config -- just tell it where to write.
        damaged_edges_path = (
            soge_clusters / "tables" / f"event_damaged_edges_{scenario_param}_{event_id}.pq"
        )
        run_script(
            "export_event_damaged_edges.py",
            [
                "--depth-key", scenario_param,
                "--event-keys", event_id,
                "--output", damaged_edges_path,
                "--results-variant", args.results_variant,
            ],
            env,
        )

        # Pass B: cheap re-solve of only the VA-area-affected candidate ODs,
        # written back into the same results variant (that's where Script 4
        # expects event_disrupted_candidates/ to live).
        pass_b_env = env.copy()
        pass_b_env["NIRD_EVENT_DAMAGED_EDGES_PATH"] = str(damaged_edges_path)
        pass_b_env["NIRD_BASELINE_PATH_OUTPUT_MODE"] = "event_candidates"
        run_script("1_network_flow_model_revision.py", [args.num_chunks, args.num_cpu], pass_b_env)

        run_script(
            "4_rerouting_and_recovery_scenario_loop.py",
            [scenario_param, event_id, args.num_chunks, args.num_cpu],
            env,
        )

    if str(VIZ_DIR) not in sys.path:
        sys.path.insert(0, str(VIZ_DIR))
    from viz_data_loaders import build_multihazard_summary_table, validate_multihazard_summary

    summary = build_multihazard_summary_table(results_root, args.results_variant, event_key=1)
    summary_path = args.summary_csv or (results_root / f"{args.results_variant}_summary.csv")
    if summary.empty:
        print("Warning: multihazard summary table is empty.", file=sys.stderr)
        return 1
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary.to_csv(summary_path, index=False)
    print(f"Wrote summary: {summary_path}")

    try:
        validate_multihazard_summary(summary, results_root=results_root, variant=args.results_variant)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
