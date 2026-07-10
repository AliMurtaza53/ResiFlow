#!/usr/bin/env python3
"""Goal 1 (CONUS extension): Pass B Script 1 numcpu sweep on VA toy raster bundle.

Uses existing smoke_50k hazard/disruption context (Track A VA toy rasters under
`soge_clusters/inputs/test_141node_50m/`). Does not modify production Script 1.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PERF_DIR = Path(__file__).resolve().parent
RUNS_ROOT = PERF_DIR / "runs"

DEFAULT_CONFIG = REPO_ROOT / "config.json"
DEFAULT_PYTHON = Path(os.environ.get("LOCALAPPDATA", "")) / "miniforge3" / "envs" / "nird" / "python.exe"
DEPTH_KEY = 30
EVENT_KEY = 1
RESULTS_VARIANT = "perf_passb_numcpu"
SAMPLE_OD_N = 50_000
MAX_FLOW_ITERATIONS = 1


def _parse_num_cpus(spec: str) -> list[int]:
    return [int(part.strip()) for part in spec.split(",") if part.strip()]


def _load_base_path(config_path: Path) -> Path:
    config = json.loads(config_path.read_text(encoding="utf-8"))
    return Path(config["paths"]["soge_clusters"])


def _build_env(
    config_path: Path,
    run_dir: Path,
    *,
    results_variant: str,
    sample_od_n: int,
    max_iters: int,
) -> dict[str, str]:
    base_path = _load_base_path(config_path)
    data_root = base_path.parent
    damaged_edges = base_path / "tables" / f"event_damaged_edges_depth{DEPTH_KEY}_toy.pq"
    lodes_assignment = (
        data_root / "lodes_data" / "processed" / "lodes_passenger_assignment_od_jt00_2022.parquet"
    )

    env = os.environ.copy()
    env["RESIFLOW_CONFIG_PATH"] = str(config_path)
    env["NIRD_CONFIG_PATH"] = str(config_path)
    env["RESIFLOW_RESULTS_VARIANT"] = results_variant
    env["NIRD_RESULTS_VARIANT"] = results_variant

    env["RESIFLOW_MAX_FLOW_ITERATIONS"] = str(max_iters)
    env["NIRD_MAX_FLOW_ITERATIONS"] = str(max_iters)
    env["RESIFLOW_SAMPLE_OD_N"] = str(sample_od_n)
    env["NIRD_SAMPLE_OD_N"] = str(sample_od_n)

    env["NIRD_PATH_REALIZATION_STRATEGY"] = "streaming_arrays"
    env["NIRD_DIRECT_DUCKDB_OUTPUTS"] = "1"
    env["NIRD_CREATE_FULL_TEMP_FLOW_MATRIX"] = "0"
    env["NIRD_ODPFC_OUTPUT_MODE"] = "skip"
    env["NIRD_WRITE_FULL_ODPFC"] = "0"
    env["NIRD_COMBINE_EVENT_CANDIDATE_PARTS"] = "0"
    env["NIRD_ENABLE_SPLIT_CACHE"] = "1"
    env["NIRD_VECTORIZE_PATH_PARSING"] = "1"
    env["NIRD_OD_ID_AT_INSERT"] = "1"
    env["NIRD_POOL_MAX_TASKS_PER_CHILD"] = "50"
    env["OMP_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"

    env["NIRD_PASSENGER_OD_PATH"] = str(lodes_assignment)
    env["RESIFLOW_PASSENGER_OD_PATH"] = str(lodes_assignment)
    env["NIRD_ENABLE_PASSENGER_REROUTING"] = "1"
    env["RESIFLOW_ENABLE_PASSENGER_REROUTING"] = "1"
    env.pop("RESIFLOW_DISABLE_PASSENGER_OD", None)
    env.pop("NIRD_DISABLE_PASSENGER_OD", None)

    env["NIRD_BASELINE_PATH_OUTPUT_MODE"] = "event_candidates"
    env["NIRD_EVENT_DAMAGED_EDGES_PATH"] = str(damaged_edges)
    env["NIRD_BASELINE_DB_PATH"] = str(run_dir / "baseline.duckdb")
    env["NIRD_BASE_SCENARIO_OUT_DIR"] = str(run_dir / "base_scenario")

    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + str(REPO_ROOT)
    return env


def _preflight(config_path: Path) -> None:
    base_path = _load_base_path(config_path)
    data_root = base_path.parent
    required = [
        base_path / "networks" / "faf5" / "faf5_road_links.gpq",
        base_path / "census_datasets" / "faf5_od_matrix.pq",
        base_path / "inputs" / "test_141node_50m" / "va_hazard_class50_141node_base.tif",
        base_path / "tables" / f"event_damaged_edges_depth{DEPTH_KEY}_toy.pq",
        data_root / "lodes_data" / "processed" / "lodes_passenger_assignment_od_jt00_2022.parquet",
    ]
    missing = [str(p) for p in required if not p.exists()]
    if missing:
        raise FileNotFoundError(
            "CONUS perf preflight failed. Missing:\n  " + "\n  ".join(missing)
        )


def _run_one(
    num_cpu: int,
    *,
    python: Path,
    config_path: Path,
    num_chunks: int,
    label: str,
    results_variant: str,
    sample_od_n: int,
    max_iters: int,
) -> Path:
    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_ROOT / f"{label}_cpu{num_cpu}_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    env = _build_env(
        config_path,
        run_dir,
        results_variant=results_variant,
        sample_od_n=sample_od_n,
        max_iters=max_iters,
    )

    meta: dict[str, object] = {
        "label": label,
        "mode": "pass_b_conus_va_toy",
        "num_cpu": num_cpu,
        "num_chunks": num_chunks,
        "sample_od_n": sample_od_n,
        "max_flow_iterations": max_iters,
        "results_variant": results_variant,
        "hazard_raster_dir": str(
            _load_base_path(config_path) / "inputs" / "test_141node_50m"
        ),
        "track_a_note": (
            "VA toy rasters (141-node footprint) stand in for state-sized Track A "
            "moving-window hazard intersection at CONUS network scale."
        ),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    log_path = run_dir / "script1_passb.log"
    cmd = [
        str(python),
        str(REPO_ROOT / "scripts" / "1_network_flow_model_revision.py"),
        str(num_chunks),
        str(num_cpu),
    ]

    wall_start = time.perf_counter()
    proc = subprocess.Popen(
        cmd,
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    stdout, _ = proc.communicate()
    wall_sec = time.perf_counter() - wall_start
    log_path.write_text(stdout or "", encoding="utf-8")

    if proc.returncode != 0:
        meta["error"] = f"exit_code={proc.returncode}"
        meta["wall_clock_sec"] = round(wall_sec, 3)
        (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        raise subprocess.CalledProcessError(proc.returncode, cmd, output=stdout)

    meta["wall_clock_sec"] = round(wall_sec, 3)
    meta["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")

    subprocess.run(
        [
            sys.executable,
            str(PERF_DIR / "parse_assignment_timing.py"),
            str(log_path),
            "--json-out",
            str(run_dir / "parsed_timing.json"),
        ],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    meta["parsed_timing"] = json.loads((run_dir / "parsed_timing.json").read_text(encoding="utf-8"))
    db = run_dir / "baseline.duckdb"
    if db.exists():
        meta["baseline_duckdb_bytes"] = db.stat().st_size
    (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    print(f"cpu={num_cpu} wall={wall_sec:.1f}s -> {run_dir}")
    return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--num-cpus", default="1,2")
    parser.add_argument("--num-chunks", type=int, default=20)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--python", type=Path, default=DEFAULT_PYTHON)
    parser.add_argument("--sample-od-n", type=int, default=SAMPLE_OD_N)
    parser.add_argument("--max-flow-iterations", type=int, default=MAX_FLOW_ITERATIONS)
    parser.add_argument("--results-variant", default=RESULTS_VARIANT)
    parser.add_argument("--label", default="goal1_conus_passb")
    args = parser.parse_args()

    if not args.config.exists():
        raise SystemExit(f"config.json not found: {args.config}")
    if not args.python.exists():
        raise SystemExit(
            f"Python not found: {args.python}. Set --python or install miniforge env 'nird'."
        )

    _preflight(args.config)
    RUNS_ROOT.mkdir(parents=True, exist_ok=True)

    for num_cpu in _parse_num_cpus(args.num_cpus):
        _run_one(
            num_cpu,
            python=args.python,
            config_path=args.config,
            num_chunks=args.num_chunks,
            label=args.label,
            results_variant=args.results_variant,
            sample_od_n=args.sample_od_n,
            max_iters=args.max_flow_iterations,
        )
    print(f"Done. Runs under {RUNS_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
