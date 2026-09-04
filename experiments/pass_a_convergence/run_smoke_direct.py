#!/usr/bin/env python3
"""Run a Pass A CONUS smoke sample in-process (no subprocess buffering) so
output streams live to whatever terminal invokes this script.

Usage:
    python run_smoke_direct.py SAMPLE_OD_N MAX_FLOW_ITERATIONS [LABEL] [NUM_CPU] [NUM_CHUNK]

Do not pass -u (unbuffered) under Start-Process redirection on Windows --
triggers a low-level CPython crash unrelated to this codebase; use
Tee-Object in the launching shell instead for live output.
"""
from __future__ import annotations

import os
import runpy
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PERF_DIR = REPO_ROOT / "experiments" / "perf_numcpu"
sys.path.insert(0, str(PERF_DIR))
from benchmark_conus_passb_numcpu import _build_env, _preflight, DEFAULT_CONFIG  # noqa: E402


def main() -> None:
    sample_od_n = int(sys.argv[1]) if len(sys.argv) > 1 else 50_000
    max_iters = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    label = sys.argv[3] if len(sys.argv) > 3 else f"smoke_{sample_od_n}_{time.strftime('%Y%m%d_%H%M%S')}"
    num_cpu = int(sys.argv[4]) if len(sys.argv) > 4 else 1
    num_chunk = int(sys.argv[5]) if len(sys.argv) > 5 else 20

    _preflight(DEFAULT_CONFIG)
    run_dir = Path(__file__).resolve().parent / "runs" / label
    run_dir.mkdir(parents=True, exist_ok=True)
    env = _build_env(
        DEFAULT_CONFIG,
        run_dir,
        results_variant=label,
        sample_od_n=sample_od_n,
        max_iters=max_iters,
    )
    for k, v in env.items():
        os.environ[k] = v

    print(
        f"[run_smoke_direct] label={label} sample_od_n={sample_od_n} "
        f"max_iters={max_iters} num_cpu={num_cpu} num_chunk={num_chunk}",
        file=sys.stderr,
    )
    print(f"[run_smoke_direct] run_dir={run_dir}", file=sys.stderr)

    sys.path.insert(0, str(REPO_ROOT / "src"))
    sys.path.insert(0, str(REPO_ROOT))
    os.chdir(REPO_ROOT)
    script_path = str(REPO_ROOT / "scripts" / "1_network_flow_model_revision.py")
    sys.argv = [script_path, str(num_chunk), str(num_cpu)]

    t0 = time.perf_counter()
    runpy.run_path(script_path, run_name="__main__")
    wall = time.perf_counter() - t0
    print(f"[run_smoke_direct] DONE label={label} wall_sec={wall:.2f}", file=sys.stderr)
    (run_dir / "wall_sec.txt").write_text(f"{wall:.3f}\n", encoding="utf-8")


if __name__ == "__main__":
    main()
