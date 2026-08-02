#!/usr/bin/env python3
"""Orchestrate the real VA multi-hazard comparison against a CONUS baseline.

Unlike scripts/testbed/run_multihazard_sioux_falls.py (synthetic toy network,
builds its own workspace), this points at a completed CONUS Pass A baseline
(edge_flows.gpq / odpfc.pq under
<soge_clusters parent>/results/base_scenario/<results-variant>/) -- see
experiments/pass_a_convergence/hopper/submit_cpu8_bounded18.slurm. This
script does NOT run Pass A; it runs the per-hazard disruption/damage/
rerouting sequence:

    Script 2 (disruption) -> Script 3 + 3_postprocess (direct damage) ->
    Script 4 (indirect/rerouting cost, combines with direct)

NO Pass B step. An earlier version of this script ran Script 1 a second time
per event in "event_candidates" mode ("Pass B"), intended as a cheap re-solve
of only the ODs affected by that event's damaged edges. It wasn't cheap:
NIRD_BASELINE_PATH_OUTPUT_MODE=event_candidates only filters what gets
WRITTEN after routing -- the LCP dispatch and OD-path realization still
cold-start over the ENTIRE CONUS demand, with no capacity reduction applied
for the damaged edge at all (Script 1 never merges disruption/damage info
into road_links for that mode -- capacity reduction only happens inside
Script 4). So Pass B was solving the exact same problem Pass A already
solved, just less converged, for real compute cost (confirmed OOM/time-limit
failures on Hopper, 2026-07-29/30).

Script 4 (scripts/4_rerouting_and_recovery_scenario_loop.py) already has a
fallback chain for exactly this situation (see its main(), ~line 505+):
legacy per-event odpfc -> Pass B's event_disrupted_candidates (now unused) ->
**the baseline's own odpfc.pq** -- i.e. Pass A's already-computed, already-
converged output -- -> odpfc_parts -> path_index artifacts. Since this
script uses one shared --results-variant for both the baseline and this
run's own outputs, that odpfc.pq fallback points directly at the real Pass A
baseline. The only fix needed was load_odpfc_source() in Script 4, which
used to load the WHOLE odpfc file into memory (fine for a small toy
baseline, not for a CONUS-scale one) -- it's now a DuckDB query filtered to
only the OD rows whose path crosses a damaged edge, same shape as the
existing path_index fallback's query. Net effect: no redundant re-solve,
*more* accurate (uses Pass A's full convergence, not a bounded Pass B),
and much faster.

Every step -- reading the Pass A baseline AND writing this run's own
disruption/damage/rerouting outputs -- uses the SAME --results-variant.
This mirrors scripts/testbed/run_multihazard_sioux_falls.py's proven
single-variant pattern (see MULTIHAZARD_VARIANT there): the pipeline's
get_results_variant() resolves one variant name for both purposes, so there
is no separate "baseline" vs. "this run" variant to plumb. Different hazard
events are told apart by scenario_param/event_id within that one variant's
folder, exactly like the toy testbed's summary table.

Hazard events are read from --hazards-manifest (schema: parameters/
hazards.va_real.example.json) rather than hardcoded, so adding/changing a
hazard is a config edit, not a code change -- this is "the one command to
regenerate everything" from docs/VA_MULTIHAZARD_COMPARISON.md.

Example::

    python scripts/run_conus_va_multihazard.py \
        --hazards-manifest /scratch/.../hazards.json \
        --results-variant convergence_cpu8_bounded18
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
        "baseline (edge_flows.gpq/odpfc.pq) -- this run's own "
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
    # Script 4's odpfc.pq fallback query AND its own internal rerouting
    # network_flow_model() call (a genuinely separate, smaller re-solve for
    # just the disrupted candidates -- not Pass B, still needed) both go
    # through the same itter_path/DuckDB aggregation code Pass A does. This
    # env var got dropped when Pass B was eliminated on the wrong assumption
    # it was Pass-B-specific tuning -- it isn't; anything calling
    # network_flow_model needs it, and its absence (silently defaulting to
    # the unchunked legacy_compact_sql strategy) caused a real OOM in
    # Script 4's rerouting step even at a much smaller scale (148K rows) than
    # CONUS-wide Pass A ever ran at (confirmed on Hopper, 2026-08-02). Full
    # config restored to match Pass A's own proven tuning
    # (submit_cpu8_bounded18.slurm). setdefault throughout so an explicit
    # SLURM wrapper's own exports still win.
    base_env.setdefault("NIRD_PATH_REALIZATION_STRATEGY", "duckdb_chunked_compact")
    base_env.setdefault("NIRD_DUCKDB_MEMORY_LIMIT", "100GB")
    base_env.setdefault("NIRD_LCP_DEST_CHUNK_SIZE", "1000")
    base_env.setdefault("NIRD_FLOW_DB_BATCH_SIZE", "50000")
    base_env.setdefault("NIRD_LCP_SORT_BY_DEST_COUNT", "1")
    base_env.setdefault(
        "NIRD_DUCKDB_TEMP_DIRECTORY", str(soge_clusters.parent / "duckdb_tmp_va_multihazard")
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
