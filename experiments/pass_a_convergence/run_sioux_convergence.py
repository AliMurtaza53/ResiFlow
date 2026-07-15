#!/usr/bin/env python3
"""Run Sioux Falls Pass A to convergence with optional fractional-remain mode."""

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
RUNS_ROOT = Path(__file__).resolve().parent / "runs"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode",
        choices=("baseline", "fractional"),
        default="baseline",
        help="baseline=full remain each iter; fractional=MSA 1/k on remain_od flows",
    )
    parser.add_argument("--max-flow-iterations", type=int, default=0)
    parser.add_argument("--label", default=None)
    args = parser.parse_args()

    label = args.label or f"sioux_{args.mode}_{int(time.time())}"
    run_dir = RUNS_ROOT / label
    run_dir.mkdir(parents=True, exist_ok=True)
    log_path = run_dir / "script1.log"

    sys.path.insert(0, str(TESTS_DIR))
    from sioux_falls_fixtures import build_sioux_falls_dataset, sioux_falls_env

    with tempfile.TemporaryDirectory(prefix="pass_a_sf_") as tmp_name:
        tmp = Path(tmp_name)
        config_path, _spec, _links = build_sioux_falls_dataset(tmp)
        env = sioux_falls_env(tmp, config_path)
        env["RESIFLOW_MAX_FLOW_ITERATIONS"] = str(args.max_flow_iterations)
        env["NIRD_MAX_FLOW_ITERATIONS"] = str(args.max_flow_iterations)
        env["NIRD_ODPFC_OUTPUT_MODE"] = "skip"
        env["NIRD_WRITE_FULL_ODPFC"] = "0"
        env["NIRD_PATH_REALIZATION_STRATEGY"] = "streaming_arrays"
        env["NIRD_DIRECT_DUCKDB_OUTPUTS"] = "1"
        env["NIRD_BASELINE_DB_PATH"] = str(run_dir / "baseline.duckdb")
        env["NIRD_BASE_SCENARIO_OUT_DIR"] = str(run_dir / "base_scenario")
        env["NIRD_BASELINE_PATH_OUTPUT_MODE"] = "none"
        env["OMP_NUM_THREADS"] = "1"
        env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + str(REPO_ROOT)
        if args.mode == "fractional":
            env["RESIFLOW_REMAIN_ASSIGN_FRACTION"] = "msa"
            env["NIRD_REMAIN_ASSIGN_FRACTION"] = "msa"

        cmd = [
            sys.executable,
            str(REPO_ROOT / "scripts" / "1_network_flow_model_revision.py"),
            "1",
            "1",
        ]
        t0 = time.perf_counter()
        proc = subprocess.run(
            cmd,
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
        )
        wall = time.perf_counter() - t0
        log_path.write_text((proc.stdout or "") + (proc.stderr or ""), encoding="utf-8")

        meta = {
            "label": label,
            "mode": args.mode,
            "wall_sec": round(wall, 3),
            "returncode": proc.returncode,
            "log_path": str(log_path),
        }
        (run_dir / "run_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        if proc.returncode != 0:
            print(proc.stdout[-2000:] if proc.stdout else "")
            print(proc.stderr[-2000:] if proc.stderr else "")
            raise SystemExit(proc.returncode)

        parse = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve().parent / "parse_assignment_log.py"),
                str(log_path),
                "--json-out",
                str(run_dir / "parsed.json"),
            ],
            cwd=REPO_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
        print(parse.stdout)
        print(f"Done -> {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
