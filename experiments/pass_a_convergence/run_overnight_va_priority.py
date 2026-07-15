#!/usr/bin/env python3
"""Overnight full-convergence Pass A run on the VA-priority 5M-OD sample
(built by build_va_priority_5m_od.py), with every validated fix from Goals
6-13 applied: threshold fix, PRAGMA threads, cap_by_eid + event-edge
vectorization, persistent LCP pool, P-core affinity, task sort by
destination-count. Unbounded iterations -- run until it stops itself or is
killed for inspection.
"""
from __future__ import annotations

import os
import runpy
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
OD_PATH = Path(__file__).resolve().parent / "runs" / "goal14_va_priority_5m_od.pq"
RUN_LABEL = "goal14_va_priority_5m_overnight"

sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT))

import pandas as pd  # noqa: E402
import resiflow.demand as demand_mod  # noqa: E402
from resiflow.demand.base import DemandLoadResult  # noqa: E402

_prebuilt_od = pd.read_parquet(OD_PATH)
print(f"[overnight] Loaded prebuilt OD: {len(_prebuilt_od):,} rows", file=sys.stderr)


def _patched_load_assignment_demand(base_path, spec=None):
    return DemandLoadResult(
        assignment_od=_prebuilt_od.copy(),
        stats={"source": "prebuilt_va_priority_5m", "combined_flow": float(_prebuilt_od["Car21"].sum())},
    )


demand_mod.load_assignment_demand = _patched_load_assignment_demand

run_dir = REPO_ROOT / "experiments" / "pass_a_convergence" / "runs" / RUN_LABEL
run_dir.mkdir(parents=True, exist_ok=True)

env = {
    "RESIFLOW_CONFIG_PATH": str(REPO_ROOT / "config.json"),
    "NIRD_CONFIG_PATH": str(REPO_ROOT / "config.json"),
    "RESIFLOW_RESULTS_VARIANT": RUN_LABEL,
    "NIRD_RESULTS_VARIANT": RUN_LABEL,
    "RESIFLOW_MAX_FLOW_ITERATIONS": "0",
    "NIRD_MAX_FLOW_ITERATIONS": "0",
    "RESIFLOW_SAMPLE_OD_N": "0",
    "NIRD_SAMPLE_OD_N": "0",
    "NIRD_PATH_REALIZATION_STRATEGY": "streaming_arrays",
    "NIRD_DIRECT_DUCKDB_OUTPUTS": "1",
    "NIRD_CREATE_FULL_TEMP_FLOW_MATRIX": "0",
    "NIRD_ODPFC_OUTPUT_MODE": "skip",
    "NIRD_WRITE_FULL_ODPFC": "0",
    "NIRD_COMBINE_EVENT_CANDIDATE_PARTS": "0",
    "NIRD_ENABLE_SPLIT_CACHE": "1",
    "NIRD_VECTORIZE_PATH_PARSING": "1",
    "NIRD_OD_ID_AT_INSERT": "1",
    # Persistent pool intentionally NOT used here: degrades badly over long
    # runs (Goal 14, notes/perf_findings/GOAL8_FULL_QUEUE_RESULTS.md §11) --
    # LCP time nearly tripled by iteration 2 in a 5M-OD test. Standard
    # per-iteration respawn pool only grew ~18% over the same 2 iterations.
    "NIRD_PERSISTENT_LCP_POOL": "0",
    "NIRD_WORKER_CPU_AFFINITY": "0 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15",
    "NIRD_POOL_MAX_TASKS_PER_CHILD": "0",
    "NIRD_LCP_SORT_BY_DEST_COUNT": "1",
    "NIRD_LCP_POOL_CHUNKSIZE": "1",
    "NIRD_BASELINE_PATH_OUTPUT_MODE": "none",
    "OMP_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
}
for k, v in env.items():
    os.environ[k] = v

print(f"[overnight] label={RUN_LABEL} num_of_cpu=4 unbounded iterations", file=sys.stderr)
print(f"[overnight] run_dir={run_dir}", file=sys.stderr)

os.chdir(REPO_ROOT)
script_path = str(REPO_ROOT / "scripts" / "1_network_flow_model_revision.py")
sys.argv = [script_path, "20", "4"]

t0 = time.perf_counter()
runpy.run_path(script_path, run_name="__main__")
wall = time.perf_counter() - t0
print(f"[overnight] DONE label={RUN_LABEL} wall_sec={wall:.2f}", file=sys.stderr)
(run_dir / "wall_sec.txt").write_text(f"{wall:.3f}\n", encoding="utf-8")
