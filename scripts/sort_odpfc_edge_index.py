#!/usr/bin/env python3
"""Sort a built (e_id, od_id) index by (e_id, od_id) to enable row-group pruning.

Root cause this fixes: build_odpfc_edge_index.py's output has no sort order,
so every filtered lookup against it (load_odpfc_source's Stage 1 hit_od_ids
build, in 4_rerouting_and_recovery_scenario_loop.py) has to scan the ENTIRE
table regardless of how few edges are being matched. Confirmed on Hopper
(2026-08-08/09): a 7-damaged-edge landslide query took ~89 minutes and up to
755GB -- the same order of magnitude as winter_storm's 11,556-edge query --
because Parquet's row-group min/max statistics can't skip anything when
e_id values are scattered essentially randomly across every row group (the
raw index was written in od_id-explosion order, not e_id order, by design --
see build_odpfc_edge_index.py's docstring on why that script deliberately
avoids a blocking ORDER BY).

Sorting by e_id makes each row group cover a narrow, non-overlapping e_id
range, so DuckDB's automatic row-group pruning (a standard technique, same
idea as min/max "zone maps" in Arrow/Spark/most columnar engines) can skip
the vast majority of row groups for any filtered query. Cost should become
roughly proportional to how many/which edges are damaged, not a fixed
full-scan floor paid by every hazard event regardless of size.

Secondary sort on od_id (within each e_id) costs almost nothing extra at
sort time (already paying for an external sort on the primary key) and
clusters the od_id values DuckDB returns from a matching row group, which
makes load_odpfc_source's Stage 2 join against odpfc.pq cheaper too.

This is a genuinely expensive, BLOCKING operation -- ORDER BY forces DuckDB
to see (and sort) the whole table before producing any output, unlike
build_odpfc_edge_index.py's deliberately-unsorted streaming explode, which
pipelines without ever materializing the full table. Expect this to spill
heavily to --temp-directory via DuckDB's external (disk-based) merge sort at
CONUS scale (~92B rows). Kept as a SEPARATE step/script from the explode so:
(a) an already-built unsorted index (e.g. convergence_cpu8_bounded18's
existing one) can be upgraded without re-paying the explode cost, and
(b) a failed/retried sort doesn't risk the already-proven explode output --
the input directory is read-only to this script.

Output is written to a NEW directory (not in-place) so it can be verified
before replacing the original -- once confirmed correct (row counts match,
EXPLAIN ANALYZE shows pruning), swap it in by renaming directories; no code
changes to load_odpfc_source are needed, since it only cares that
<baseline>/odpfc_edge_index/part_*.pq exists and has (od_id, e_id) columns,
not how it's internally sorted.

Usage (on a compute node -- see experiments/conus_multihazard/hopper/
submit_sort_edge_index.slurm)::

    python scripts/sort_odpfc_edge_index.py \
        --input /scratch/.../odpfc_edge_index \
        --output /scratch/.../odpfc_edge_index_sorted \
        --memory-limit 130GB \
        --temp-directory /scratch/.../duckdb_tmp
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import duckdb


def sort_edge_od_index(
    input_dir: Path,
    output_dir: Path,
    memory_limit: str = "90GB",
    temp_dir: str | None = None,
    threads: int | None = None,
) -> None:
    if input_dir.is_dir():
        input_sql = (input_dir / "*.pq").as_posix().replace("'", "''")
    else:
        input_sql = input_dir.as_posix().replace("'", "''")

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
    print(
        f"Sorting {input_dir} by (e_id, od_id) -> {part_path} "
        "(external/disk-spilling sort -- this is the long, expensive step)"
    )
    conn.execute(
        f"""
        COPY (
            SELECT od_id, e_id
            FROM read_parquet('{input_sql}')
            ORDER BY e_id, od_id
        ) TO '{part_sql}' (FORMAT PARQUET)
        """
    )
    total_rows = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{part_sql}')").fetchone()[0]
    conn.close()
    print(f"Wrote sorted edge/od_id index: {output_dir} ({total_rows:,} rows)")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--input", type=Path, required=True, help="Existing (unsorted) odpfc_edge_index directory")
    parser.add_argument("--output", type=Path, required=True, help="New directory for the sorted index")
    parser.add_argument("--memory-limit", default=os.environ.get("NIRD_DUCKDB_MEMORY_LIMIT", "90GB"))
    parser.add_argument("--temp-directory", default=os.environ.get("NIRD_DUCKDB_TEMP_DIRECTORY"))
    parser.add_argument("--threads", type=int, default=None)
    args = parser.parse_args()

    sort_edge_od_index(
        args.input,
        args.output,
        memory_limit=args.memory_limit,
        temp_dir=args.temp_directory,
        threads=args.threads,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
