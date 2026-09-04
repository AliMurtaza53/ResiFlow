"""Recover final outputs from a convergence run's DuckDB file without a clean stop.

network_flow_model()'s final export (odpfc.pq, trip_isolations.pq) runs AFTER the
while-loop exits via a clean break (max iterations / stagnation) -- see
road_revised.py around line 3888 onward. If SLURM kills the job mid-loop (e.g. a
--time limit), that export never runs, even though every completed iteration's
data is already durably committed to the DuckDB file on /scratch (DuckDB
auto-commits each statement outside an explicit transaction).

This script reruns the same export queries directly against that file, so
whatever iterations DID complete are not stranded. Only usable once the job has
actually stopped (crashed, cancelled, or finished) -- DuckDB does not support a
read-only connection from a second process while the run's own process still
holds the file open read-write.

IMPORTANT -- run this on a compute-node allocation (sbatch/srun), NOT on a
Hopper login node. The accumulated odpfc table across N iterations can be far
bigger than the ~9.68M-row single-iteration table that already needed ~100GB
and chunking earlier in this project (see docs/ORC_HOPPER_SETUP.md section 7)
-- login nodes are shared and memory-restricted, and this script's queries
will get silently OOM-killed there with just a bare "Killed" message and no
further detail. Use experiments/pass_a_convergence/hopper/submit_recover.slurm.

Usage (inside a compute allocation, after the job has stopped):
    python recover_convergence_output.py \
        --db /scratch/akothaw/multimodal_hazard_data/convergence_cpu8.duckdb \
        --out-dir /scratch/akothaw/multimodal_hazard_data/results/base_scenario/convergence_cpu8_recovered
"""

import argparse
import os

import duckdb


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db",
        default="/scratch/akothaw/multimodal_hazard_data/convergence_cpu8.duckdb",
        help="Path to the run's DuckDB file (NIRD_BASELINE_DB_PATH from the SLURM script).",
    )
    parser.add_argument(
        "--out-dir",
        default="/scratch/akothaw/multimodal_hazard_data/results/base_scenario/convergence_cpu8_recovered",
        help="Directory to write the recovered parquet files into.",
    )
    parser.add_argument(
        "--memory-limit",
        default=os.environ.get("NIRD_DUCKDB_MEMORY_LIMIT", "100GB"),
        help="DuckDB PRAGMA memory_limit -- same lesson as the rest of this project: "
        "unbounded aggregation over a large accumulated table risks OOM.",
    )
    parser.add_argument(
        "--temp-directory",
        default=os.environ.get("NIRD_DUCKDB_TEMP_DIRECTORY", ""),
        help="DuckDB PRAGMA temp_directory (spill target). Defaults to a directory "
        "next to --out-dir if not given.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        default=int(os.environ.get("SLURM_CPUS_PER_TASK", "8")),
        help="DuckDB PRAGMA threads.",
    )
    args = parser.parse_args()

    if not os.path.exists(args.db):
        raise SystemExit(f"DuckDB file not found: {args.db}")
    os.makedirs(args.out_dir, exist_ok=True)

    temp_dir = args.temp_directory or os.path.join(args.out_dir, "duckdb_tmp_recover")
    os.makedirs(temp_dir, exist_ok=True)

    conn = duckdb.connect(args.db, read_only=True)
    conn.execute(f"PRAGMA threads={max(1, args.threads)}")
    conn.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    conn.execute(f"PRAGMA temp_directory='{temp_dir}'")
    print(f"DuckDB: threads={args.threads}, memory_limit={args.memory_limit}, temp_directory={temp_dir}")

    tables = {r[0] for r in conn.execute("SHOW TABLES").fetchall()}
    print(f"Tables present in {args.db}: {sorted(tables)}")

    if "odpfc" in tables:
        n_raw = conn.execute("SELECT COUNT(*) FROM odpfc").fetchone()[0]
        print(f"odpfc raw row count (before GROUP BY collapse): {n_raw:,}")

    # 1. odpfc -- exact same aggregation as the official final export
    # (road_revised.py ~line 3909-3924): collapses duplicate origin/
    # destination/path rows accumulated across however many iterations
    # actually completed. Iteration-agnostic by construction -- no need
    # to know which iteration each row came from.
    if "odpfc" in tables:
        odpfc_out = os.path.join(args.out_dir, "odpfc_recovered.pq")
        conn.execute(
            f"""
            COPY (
                SELECT
                    origin AS origin_node,
                    destination AS destination_node,
                    MIN(od_id) AS od_id,
                    path,
                    SUM(flow) AS flow,
                    MIN(fuel) AS operating_cost_per_flow,
                    MIN(time) AS time_cost_per_flow,
                    MIN(toll) AS toll_cost_per_flow,
                    MIN(fare) AS fare_cost_per_flow
                FROM odpfc
                GROUP BY origin, destination, path
            ) TO '{odpfc_out}' (FORMAT PARQUET);
            """
        )
        n_rows, total_flow = conn.execute(
            "SELECT COUNT(*), COALESCE(SUM(flow), 0.0) FROM odpfc"
        ).fetchone()
        print(f"odpfc -> {odpfc_out}  ({n_rows} rows, {total_flow:,.1f} total flow)")
    else:
        print("No 'odpfc' table found -- nothing to recover for OD path flows.")

    # 2. isolated_od -- same query as the official trip_isolations.pq export
    # (road_revised.py ~line 3888-3902). Only ever populated on a clean
    # stagnation-triggered stop, so this will likely be empty for a
    # time-limit kill -- that's expected, not a bug in this script.
    if "isolated_od" in tables:
        iso_out = os.path.join(args.out_dir, "trip_isolations_recovered.pq")
        conn.execute(
            f"""
            COPY (
                SELECT
                    origin_node,
                    destination_node,
                    SUM(flow) AS flow
                FROM isolated_od
                WHERE origin_node != destination_node
                  AND flow > 0
                GROUP BY origin_node, destination_node
            ) TO '{iso_out}' (FORMAT PARQUET);
            """
        )
        n_rows = conn.execute("SELECT COUNT(*) FROM isolated_od").fetchone()[0]
        print(f"isolated_od -> {iso_out}  ({n_rows} rows)")
    else:
        print("No 'isolated_od' table found (expected unless stagnation already triggered).")

    # 3. Edge-level flow totals, derived from odpfc.path (already a list of
    # e_id values, not edge indices -- see itter_path's LIST(e.e_id ORDER BY
    # u.ord) construction). This is NOT a byte-for-byte replica of the
    # official edge_flows.gpq: that file also carries road_links' geometry
    # and the iteration-by-iteration capacity/speed-update dynamics from
    # update_network_structure(), which lived only in the run's in-memory
    # Python state and cannot be reconstructed from the DB alone. This gives
    # the core number -- cumulative flow per edge -- which can be joined
    # onto the original road_links parquet separately if geometry is needed.
    if "odpfc" in tables:
        edge_out = os.path.join(args.out_dir, "edge_flow_totals_recovered.pq")
        # DuckDB doesn't support a bare UNNEST(...) in the SELECT list
        # combined with GROUP BY (BinderException) -- has to be the same
        # CROSS JOIN UNNEST pattern road_revised.py uses everywhere else.
        conn.execute(
            f"""
            COPY (
                SELECT u.e_id, SUM(o.flow) AS total_flow
                FROM odpfc o
                CROSS JOIN UNNEST(o.path) AS u(e_id)
                GROUP BY u.e_id
            ) TO '{edge_out}' (FORMAT PARQUET);
            """
        )
        n_edges = conn.execute(
            "SELECT COUNT(DISTINCT u.e_id) FROM odpfc o CROSS JOIN UNNEST(o.path) AS u(e_id)"
        ).fetchone()[0]
        print(f"edge flow totals -> {edge_out}  ({n_edges} distinct edges)")

    conn.close()
    print("Done.")


if __name__ == "__main__":
    main()
