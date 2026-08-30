#!/bin/bash
#SBATCH --job-name=nandu_eq403_cpu128_bench
#SBATCH --partition=bigmem
# CPU-scaling benchmark, Script-4-only re-run of earthquake/403 (New Madrid).
# See submit_earthquake_403_cpu16_benchmark.slurm for the full explanation
# (back up .../403/1 first; submit sequentially, not concurrently).
# --cpus-per-task=128 alone forces SLURM onto one of bigmem's 128-core nodes
# (amd081-090) -- no 64-core node in this partition can satisfy the request,
# so no extra --constraint is needed.
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=128
#SBATCH --mem=900G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_nandu_eq403_cpu128_bench_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_nandu_eq403_cpu128_bench_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=conus_nandu_v1
export RESIFLOW_RESULTS_VARIANT=conus_nandu_v1
export NIRD_DUCKDB_MEMORY_LIMIT=800GB
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_va_multihazard_nandu
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_HAZARD_TYPE=earthquake
export RESIFLOW_SCENARIO_PARAM=403

REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow
OUT=/scratch/akothaw/multimodal_hazard_data/results/rerouting_analysis/conus_nandu_v1/403/1

python $REPO/scripts/4_rerouting_and_recovery_scenario_loop.py 403 1 320 $SLURM_CPUS_PER_TASK

mv "$OUT" "${OUT}_cpu128"
