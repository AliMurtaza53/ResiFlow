"""Sample process CPU and I/O counters during a benchmark run (optional psutil)."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path


def sample_pid(pid: int, interval_sec: float, duration_sec: float) -> dict[str, float | int]:
    try:
        import psutil
    except ImportError as exc:
        raise SystemExit(
            "psutil not installed. For perf venv only: pip install psutil"
        ) from exc

    proc = psutil.Process(pid)
    cpu_samples: list[float] = []
    read_bytes_start = write_bytes_start = None
    try:
        io_start = proc.io_counters()
        read_bytes_start = io_start.read_bytes
        write_bytes_start = io_start.write_bytes
    except (psutil.AccessDenied, AttributeError):
        pass

    deadline = time.time() + duration_sec
    logical_cpus = psutil.cpu_count(logical=True) or 1
    while time.time() < deadline:
        try:
            cpu_samples.append(proc.cpu_percent(interval=None))
        except psutil.NoSuchProcess:
            break
        time.sleep(interval_sec)

    read_delta = write_delta = 0
    try:
        io_end = proc.io_counters()
        if read_bytes_start is not None:
            read_delta = io_end.read_bytes - read_bytes_start
        if write_bytes_start is not None:
            write_delta = io_end.write_bytes - write_bytes_start
    except (psutil.AccessDenied, AttributeError, psutil.NoSuchProcess):
        pass

    avg_cpu = sum(cpu_samples) / len(cpu_samples) if cpu_samples else 0.0
    # cpu_percent is per-logical-core; normalize to fraction of machine
    avg_cpu_fraction = avg_cpu / (100.0 * logical_cpus)
    return {
        "samples": len(cpu_samples),
        "avg_cpu_percent_of_one_core": round(avg_cpu, 2),
        "avg_cpu_fraction_of_machine": round(avg_cpu_fraction, 4),
        "logical_cpus": logical_cpus,
        "read_bytes_delta": read_delta,
        "write_bytes_delta": write_delta,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--duration", type=float, default=600.0)
    parser.add_argument("--json-out", type=Path, required=True)
    args = parser.parse_args()
    stats = sample_pid(args.pid, args.interval, args.duration)
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(stats, indent=2), encoding="utf-8")
    print(json.dumps(stats, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
