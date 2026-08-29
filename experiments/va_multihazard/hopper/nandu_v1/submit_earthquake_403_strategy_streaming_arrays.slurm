#!/bin/bash
#SBATCH --job-name=nandu_eq403_strat_streaming
#SBATCH --partition=bigmem
# Path-realization STRATEGY A/B test, not a CPU-scaling test -- same 8 CPUs,
# same everything else as the original production run, only
# NIRD_PATH_REALIZATION_STRATEGY changed from duckdb_chunked_compact
# (current production default, every Script 4 job to date) to
# streaming_arrays.
#
# WHY: notes/perf_findings/GOAL8_FULL_QUEUE_RESULTS.md (branch
# perf/lcp-dest-chunked-dispatch, merged into this branch's history) directly
# benchmarked duckdb_chunked_compact against streaming_arrays on Script 1's
# Pass A workload and explicitly abandoned duckdb_chunked_compact as a
# production candidate: slower overall, and scales NEGATIVELY with CPU count
# (1052s->1909s going 1->4 CPUs). That finding was never carried into Script
# 4's SLURM configs, which still hard-code duckdb_chunked_compact today.
# Script 4 calls the same underlying network_flow_model()/
# realize_paths_streaming() functions Script 1 does, so this is worth testing
# directly before any CPU-count benchmarking -- if streaming_arrays is faster
# here too, it's a bigger win than any core-count change, and CPU-scaling
# numbers measured against the wrong strategy would be meaningless anyway.
#
# IMPORTANT -- back up the current 403 output before running this (same
# reason as the cpu-scaling benchmark jobs): Script 4 writes to the same
# path regardless of strategy.
#   mv .../rerouting_analysis/conus_nandu_v1/403/1 .../403/1_baseline_8cpu_backup
# (skip this if you already did it for the cpu-scaling jobs and haven't
# restored it yet -- just don't run this concurrently with those jobs, same
# output-path collision risk.)
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=900G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_nandu_eq403_strat_streaming_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_nandu_eq403_strat_streaming_%j.err
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

python $REPO/scripts/4_rerouting_and_recovery_scenario_loop.py 403 1 20 $SLURM_CPUS_PER_TASK

mv "$OUT" "${OUT}_strategy_streaming_arrays"
