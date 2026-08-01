#!/usr/bin/env python3
"""Build a persistent (e_id, od_id) index from a baseline's odpfc.pq, once.

Root cause this fixes: Script 4's candidate-lookup fallback
(load_odpfc_source in 4_rerouting_and_recovery_scenario_loop.py) has to
CROSS JOIN UNNEST(path) over the ENTIRE baseline odpfc table to find which
OD pairs touch a hazard event's damaged edges -- and it was doing this from
scratch for EVERY hazard event (up to 4x for this project), even though the
explode step touches every edge of every one of the baseline's ~9.68M paths
regardless of how many edges you're actually matching against. Confirmed on
Hopper (2026-08-01): a hazard with 95 damaged edges ran 6+ hours without
finishing on the direct-UNNEST approach, having presumably taken a similar
(unmeasured, interrupted-by-OOM) amount of time for a 1-damaged-edge hazard
a day earlier.

This script does the expensive explode exactly ONCE and streams it straight
to parquet via a single COPY (no fetchdf() materialization into Python
memory). Script 4's loader then does a cheap filtered lookup against this
index instead of re-exploding per event.

An earlier version of this script chunked by od_id range
(``WHERE o.od_id BETWEEN start AND end``) to bound memory and show visible
progress. That backfired badly on Hopper (2026-08-01): 3 of 346 chunks
completed in 4h10m (~83 min/chunk -- ~20 days projected). The WHERE filter
does not appear to push down through CROSS JOIN UNNEST, so every chunk was
re-exploding the ENTIRE ~9.68M-row (well beyond that once accumulated
across 18 iterations) table before filtering -- 346x the cost of doing it
once, not a bounded subset of it. Fixed by dropping value-based chunking
entirely: DuckDB's push-based vectorized execution should pipeline a plain
project+explode+COPY (no blocking DISTINCT/GROUP BY/ORDER BY) without
materializing the full exploded output in memory -- memory is bounded by
internal buffer/vector and parquet-writer row-group sizes, not by total
output size. This trades away per-chunk progress visibility for paying the
explode cost exactly once instead of 346 times.

Usage (on a compute node, not the login node -- see submit_build_edge_index.slurm)::

    python scripts/build_odpfc_edge_index.py \
        --odpfc /scratch/.../results/base_scenario/convergence_cpu8_bounded18/odpfc.pq \
        --output /scratch/.../results/base_scenario/convergence_cpu8_bounded18/odpfc_edge_index
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import duckdb


def build_edge_od_index(
    odpfc_path: Path,
    output_dir: Path,
    memory_limit: str = "90GB",
    temp_dir: str | None = None,
    threads: int | None = None,
) -> None:
    if odpfc_path.is_dir():
        odpfc_sql = (odpfc_path / "*.pq").as_posix().replace("'", "''")
    else:
        odpfc_sql = odpfc_path.as_posix().replace("'", "''")
    conn = duckdb.connect()
    if threads:
        conn.execute(f"PRAGMA threads={int(threads)}")
    conn.execute(f"PRAGMA memory_limit='{memory_limit}'")
    conn.execute("PRAGMA preserve_insertion_order=false")
    if temp_dir:
        conn.execute(f"PRAGMA temp_directory='{temp_dir}'")

    output_dir.mkdir(parents=True, exist_ok=True)
    part_path = output_dir / "part_000000000000.pq"
    part_sql = str(part_path).replace("'", "''")
    print(f"Streaming explode -> {part_path} (single pass, no chunking; this is the long step)")
    conn.execute(
        f"""
        COPY (
            SELECT o.od_id, u.e_id
            FROM read_parquet('{odpfc_sql}') o
            CROSS JOIN UNNEST(o.path) AS u(e_id)
        ) TO '{part_sql}' (FORMAT PARQUET)
        """
    )
    total_rows = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{part_sql}')").fetchone()[0]
    conn.close()
    print(f"Wrote edge/od_id index: {output_dir} ({total_rows:,} rows)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--odpfc", type=Path, required=True, help="Path to the baseline's odpfc.pq")
    parser.add_argument("--output", type=Path, required=True, help="Output directory for index parts")
    parser.add_argument("--memory-limit", default=os.environ.get("NIRD_DUCKDB_MEMORY_LIMIT", "90GB"))
    parser.add_argument("--temp-directory", default=os.environ.get("NIRD_DUCKDB_TEMP_DIRECTORY"))
    parser.add_argument("--threads", type=int, default=None)
    args = parser.parse_args()

    build_edge_od_index(
        args.odpfc,
        args.output,
        memory_limit=args.memory_limit,
        temp_dir=args.temp_directory,
        threads=args.threads,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
