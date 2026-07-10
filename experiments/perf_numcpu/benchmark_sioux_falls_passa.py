#!/usr/bin/env python3
"""Goal 1: Sioux Falls Pass A numcpu sweep with wall-clock + optional CPU sampling.

Does not modify production Script 1. Uses pytest Sioux Falls fixtures in a temp workspace.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"
PERF_DIR = Path(__file__).resolve().parent
RUNS_ROOT = PERF_DIR / "runs"


def _parse_num_cpus(spec: str) -> list[int]:
    return [int(part.strip()) for part in spec.split(",") if part.strip()]


def _build_env(tmp: Path, config_path: Path, run_dir: Path, *, max_iters: int) -> dict[str, str]:
    sys.path.insert(0, str(TESTS_DIR))
    from sioux_falls_fixtures import sioux_falls_env

    env = sioux_falls_env(tmp, config_path)
    env["NIRD_MAX_FLOW_ITERATIONS"] = str(max_iters)
    env["RESIFLOW_MAX_FLOW_ITERATIONS"] = str(max_iters)
    env["NIRD_PATH_REALIZATION_STRATEGY"] = "streaming_arrays"
    env["NIRD_DIRECT_DUCKDB_OUTPUTS"] = "1"
    env["NIRD_ODPFC_OUTPUT_MODE"] = "skip"
    env["NIRD_WRITE_FULL_ODPFC"] = "0"
    env["NIRD_OD_ID_AT_INSERT"] = "1"
    env["NIRD_BASELINE_DB_PATH"] = str(run_dir / "baseline.duckdb")
    env["NIRD_BASE_SCENARIO_OUT_DIR"] = str(run_dir / "base_scenario")
    env["OMP_NUM_THREADS"] = "1"
    env["MKL_NUM_THREADS"] = "1"
    env["OPENBLAS_NUM_THREADS"] = "1"
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + str(REPO_ROOT)
    return env


def _run_one(num_cpu: int, *, max_iters: int, num_chunks: int, label: str) -> Path:
    import shutil

    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_ROOT / f"{label}_cpu{num_cpu}_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(TESTS_DIR))
    from sioux_falls_fixtures import build_sioux_falls_dataset

    with tempfile.TemporaryDirectory(prefix="perf_sf_") as tmp_name:
        tmp = Path(tmp_name)
        config_path, _spec, _links = build_sioux_falls_dataset(tmp)
        env = _build_env(tmp, config_path, run_dir, max_iters=max_iters)

        log_path = run_dir / "script1.log"
        meta: dict[str, object] = {
            "label": label,
            "num_cpu": num_cpu,
            "num_chunks": num_chunks,
            "max_flow_iterations": max_iters,
            "mode": "pass_a_sioux_falls",
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        cmd = [
            sys.executable,
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

        sampler_proc = None
        sampler_path = run_dir / "cpu_samples.json"
        try:
            import psutil  # noqa: F401

            sampler_proc = subprocess.Popen(
                [
                    sys.executable,
                    str(PERF_DIR / "cpu_monitor.py"),
                    "--pid",
                    str(proc.pid),
                    "--interval",
                    "0.5",
                    "--duration",
                    "3600",
                    "--json-out",
                    str(sampler_path),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            sampler_proc = None

        stdout, _ = proc.communicate()
        wall_sec = time.perf_counter() - wall_start
        log_path.write_text(stdout or "", encoding="utf-8")

        if sampler_proc is not None:
            sampler_proc.terminate()
            try:
                sampler_proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                sampler_proc.kill()

        if proc.returncode != 0:
            meta["error"] = f"exit_code={proc.returncode}"
            (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            raise subprocess.CalledProcessError(proc.returncode, cmd, output=stdout)

        meta["wall_clock_sec"] = round(wall_sec, 3)
        meta["completed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        if sampler_path.exists():
            meta["cpu_samples"] = json.loads(sampler_path.read_text(encoding="utf-8"))
        else:
            meta["cpu_samples"] = {"note": "psutil sampler unavailable"}

        parsed = subprocess.run(
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
        (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        # Copy duckdb size hint
        db = run_dir / "baseline.duckdb"
        if db.exists():
            meta["baseline_duckdb_bytes"] = db.stat().st_size
            (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        print(f"cpu={num_cpu} wall={wall_sec:.2f}s -> {run_dir}")
        return run_dir


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--num-cpus", default="1,2,4,8,16")
    parser.add_argument("--max-flow-iterations", type=int, default=1)
    parser.add_argument("--num-chunks", type=int, default=1)
    parser.add_argument("--label", default="goal1_sioux_passa")
    args = parser.parse_args()

    RUNS_ROOT.mkdir(parents=True, exist_ok=True)
    for num_cpu in _parse_num_cpus(args.num_cpus):
        _run_one(
            num_cpu,
            max_iters=args.max_flow_iterations,
            num_chunks=args.num_chunks,
            label=args.label,
        )
    print(f"Done. Runs under {RUNS_ROOT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
