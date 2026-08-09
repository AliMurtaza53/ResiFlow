#!/bin/bash
#SBATCH --job-name=verify_edge_index_sort
#SBATCH --partition=normal
# Cheap, fast verification that scripts/sort_odpfc_edge_index.py's approach
# actually works BEFORE spending real time/money re-sorting the production
# convergence_cpu8_bounded18 index (92B rows, ~386GB). Runs against a small
# baseline's odpfc.pq, builds an unsorted edge index (if one doesn't already
# exist), sorts it, then runs EXPLAIN ANALYZE on the same filtered query
# load_odpfc_source's Stage 1 runs, comparing rows-scanned between the two.
#
# Verified locally (2026-08-09, 39.2M-row toy index): sorting cut rows
# scanned by the TABLE_SCAN node from 36,932,943 to 741,568 (~49.8x fewer)
# for a 7-edge filter, with identical query results (18,597 distinct od_id
# either way) -- this job re-confirms the same mechanism holds in Hopper's
# own DuckDB/filesystem environment before trusting it on CONUS scale.
#
# TOY_ODPFC below defaults to the "revision" baseline path used earlier
# this session for validation -- if that path doesn't exist on Hopper,
# point this at any other small, already-completed baseline's odpfc.pq
# (does not need to be VA/CONUS -- any real odpfc.pq works for this check).
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=32G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_verify_edge_sort_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_verify_edge_sort_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow
TOY_ODPFC=/scratch/akothaw/multimodal_hazard_data/results/base_scenario/revision/odpfc.pq
WORKDIR=/scratch/akothaw/multimodal_hazard_data/edge_index_verify_test

mkdir -p "$WORKDIR"

if [ ! -f "$WORKDIR/unsorted/part_000000000000.pq" ]; then
  python "$REPO/scripts/build_odpfc_edge_index.py" \
    --odpfc "$TOY_ODPFC" \
    --output "$WORKDIR/unsorted" \
    --memory-limit 16GB
fi

python "$REPO/scripts/sort_odpfc_edge_index.py" \
  --input "$WORKDIR/unsorted" \
  --output "$WORKDIR/sorted" \
  --memory-limit 16GB

python - <<'PYEOF'
import duckdb

workdir = "/scratch/akothaw/multimodal_hazard_data/edge_index_verify_test"
conn = duckdb.connect()
sample_edges = conn.execute(
    f"SELECT DISTINCT e_id FROM read_parquet('{workdir}/unsorted/part_*.pq') USING SAMPLE 7 ROWS"
).fetchdf()
print("sample damaged edges:", sample_edges["e_id"].tolist())
conn.register("damaged_edges", sample_edges)

results = {}
for label in ["unsorted", "sorted"]:
    q = f"""
        SELECT DISTINCT idx.od_id
        FROM read_parquet('{workdir}/{label}/part_*.pq') idx
        JOIN damaged_edges d ON d.e_id = idx.e_id
    """
    res = conn.execute(q).fetchdf()
    results[label] = set(res["od_id"].tolist())
    print(f"{label}: {len(res)} distinct od_id")

    plan = conn.execute("EXPLAIN ANALYZE " + q).fetchdf()
    text = "\n".join(str(v) for row in plan.itertuples(index=False) for v in row)
    for line in text.splitlines():
        if "rows" in line.lower() and ("scan" in text.lower()):
            pass  # full plan printed below regardless
    print(text)
    print()

assert results["unsorted"] == results["sorted"], "MISMATCH -- sorted index produced different results!"
print("CORRECTNESS CONFIRMED: unsorted and sorted indexes produced identical results.")
print("Check the TABLE_SCAN 'rows' figures above under each READ_PARQUET node --")
print("sorted should show dramatically fewer rows scanned than unsorted for the same filter.")
PYEOF
