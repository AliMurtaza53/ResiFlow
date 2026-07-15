#!/usr/bin/env python3
"""Short CONUS Pass A convergence sample (50k OD) for baseline vs MSA remain mode."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PERF_DIR = REPO_ROOT / "experiments" / "perf_numcpu"
RUNS_ROOT = Path(__file__).resolve().parent / "runs"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("baseline", "fractional"), default="baseline")
    parser.add_argument("--max-flow-iterations", type=int, default=15)
    parser.add_argument("--sample-od-n", type=int, default=50000)
    parser.add_argument("--label", default=None)
    args = parser.parse_args()

    label = args.label or f"conus_{args.mode}_{int(time.time())}"
    run_dir = RUNS_ROOT / label
    run_dir.mkdir(parents=True, exist_ok=True)

    python = Path(os.environ.get("LOCALAPPDATA", "")) / "miniforge3" / "envs" / "nird" / "python.exe"
    if not python.exists():
        python = Path(sys.executable)

    cmd = [
        str(python),
        str(PERF_DIR / "benchmark_conus_passb_numcpu.py"),
        "--num-cpus",
        "1",
        "--max-flow-iterations",
        str(args.max_flow_iterations),
        "--sample-od-n",
        str(args.sample_od_n),
        "--results-variant",
        f"pass_a_conv_{label}",
        "--label",
        label,
    ]
    env = os.environ.copy()
    env["NIRD_BASELINE_PATH_OUTPUT_MODE"] = "none"
    env["RESIFLOW_MAX_FLOW_ITERATIONS"] = str(args.max_flow_iterations)
    env["NIRD_MAX_FLOW_ITERATIONS"] = str(args.max_flow_iterations)
    if args.mode == "fractional":
        env["RESIFLOW_REMAIN_ASSIGN_FRACTION"] = "msa"
        env["NIRD_REMAIN_ASSIGN_FRACTION"] = "msa"

    # Pass A only: run Script 1 directly with Pass A env (not Pass B)
    config_path = REPO_ROOT / "config.json"
    if not config_path.exists():
        raise SystemExit("config.json required for CONUS sample run")

    sys.path.insert(0, str(PERF_DIR))
    from benchmark_conus_passb_numcpu import _build_env, _preflight, _load_base_path

    _preflight(config_path)
    env = _build_env(
        config_path,
        run_dir,
        results_variant=f"pass_a_conv_{label}",
        sample_od_n=args.sample_od_n,
        max_iters=args.max_flow_iterations,
    )
    env["NIRD_BASELINE_PATH_OUTPUT_MODE"] = "none"
    env.pop("NIRD_EVENT_DAMAGED_EDGES_PATH", None)
    if args.mode == "fractional":
        env["RESIFLOW_REMAIN_ASSIGN_FRACTION"] = "msa"
        env["NIRD_REMAIN_ASSIGN_FRACTION"] = "msa"

    log_path = run_dir / "script1_passa.log"
    script_cmd = [
        str(python),
        str(REPO_ROOT / "scripts" / "1_network_flow_model_revision.py"),
        "20",
        "1",
    ]
    proc = subprocess.run(script_cmd, cwd=REPO_ROOT, env=env, capture_output=True, text=True)
    log_path.write_text((proc.stdout or "") + (proc.stderr or ""), encoding="utf-8")
    if proc.returncode != 0:
        raise SystemExit(proc.returncode)

    parse = subprocess.run(
        [
            sys.executable,
            str(Path(__file__).resolve().parent / "parse_assignment_log.py"),
            str(log_path),
            "--json-out",
            str(run_dir / "parsed.json"),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    print(parse.stdout)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
