#!/usr/bin/env python3
"""Goal 2: isolate pool overhead, affinity, and LCP-collect modes (scratch only)."""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
from multiprocessing import Pool
from pathlib import Path

PERF_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PERF_DIR))
sys.path.insert(0, str(PERF_DIR.parents[1] / "src"))

from sioux_context import build_sioux_lcp_context
from resiflow import road_revised as rr

RUNS_ROOT = PERF_DIR / "runs"


def _env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def _worker_init(shared_network_pkl: bytes) -> None:
    rr.worker_init_path(shared_network_pkl)
    affinity = os.environ.get("PERF_WORKER_CPU_AFFINITY", "").strip()
    if not affinity:
        return
    try:
        import psutil

        cores = [int(x) for x in affinity.split(",") if x.strip()]
        psutil.Process().cpu_affinity(cores)
    except Exception:
        pass


def _run_pool(
    network,
    args: list[tuple],
    *,
    num_cpu: int,
    stream_inserts: bool,
) -> dict[str, float | int]:
    shared_network_pkl = pickle.dumps(network)
    pool_kwargs = {
        "processes": max(1, num_cpu),
        "initializer": _worker_init,
        "initargs": (shared_network_pkl,),
    }
    recycle = int(os.environ.get("NIRD_POOL_MAX_TASKS_PER_CHILD", "0"))
    if recycle > 0:
        pool_kwargs["maxtasksperchild"] = recycle

    results: list[tuple] = []
    t0 = time.perf_counter()
    if num_cpu <= 1:
        rr.shared_network = network  # type: ignore[attr-defined]
        for arg in args:
            results.append(rr.find_least_cost_path(arg))
    else:
        with Pool(**pool_kwargs) as pool:
            if stream_inserts:
                count = 0
                for sp in pool.imap_unordered(rr.find_least_cost_path, args):
                    count += 1
                    results.append(sp)
            else:
                results = list(pool.imap_unordered(rr.find_least_cost_path, args))
    lcp_sec = time.perf_counter() - t0

    # Simulate main-process insert work (no DuckDB): count path rows
    path_rows = sum(len(p[2]) for p in results)
    return {
        "num_cpu": num_cpu,
        "stream_inserts": int(stream_inserts),
        "lcp_wall_sec": round(lcp_sec, 4),
        "path_rows": path_rows,
        "tasks": len(args),
    }


def _benchmark_pickle(network, *, repeats: int = 20) -> float:
    t0 = time.perf_counter()
    blob = pickle.dumps(network)
    for _ in range(repeats):
        pickle.loads(blob)
    return (time.perf_counter() - t0) / repeats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin-replicas", type=int, default=1)
    parser.add_argument("--num-cpus", default="1,2,4")
    parser.add_argument("--label", default="goal2_pool_isolation")
    parser.add_argument(
        "--affinity",
        help="Comma-separated logical CPU ids for PERF_WORKER_CPU_AFFINITY (optional)",
    )
    args_cli = parser.parse_args()

    if args_cli.affinity:
        os.environ["PERF_WORKER_CPU_AFFINITY"] = args_cli.affinity

    network, args, stats = build_sioux_lcp_context(origin_replicas=args_cli.origin_replicas)
    pickle_sec = _benchmark_pickle(network)

    stamp = time.strftime("%Y%m%d_%H%M%S")
    run_dir = RUNS_ROOT / f"{args_cli.label}_rep{args_cli.origin_replicas}_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    for num_cpu in [int(x) for x in args_cli.num_cpus.split(",") if x.strip()]:
        for stream in (True, False):
            row = _run_pool(network, args, num_cpu=num_cpu, stream_inserts=stream)
            row["mode"] = "stream_insert" if stream else "collect_then_insert"
            rows.append(row)

    out = {
        "stats": stats,
        "avg_pickle_load_sec_per_worker": round(pickle_sec, 6),
        "duckdb_contention_note": (
            "Production LCP workers do not write DuckDB; inserts run in main process. "
            "collect_then_insert mode simulates NIRD_LCP_COLLECT_POOL_RESULTS=1 RAM pattern."
        ),
        "affinity": os.environ.get("PERF_WORKER_CPU_AFFINITY", ""),
        "rows": rows,
    }
    out_path = run_dir / "goal2_pool_isolation.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps(out, indent=2))
    print(f"Wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
