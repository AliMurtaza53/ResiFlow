#!/bin/bash
#SBATCH --job-name=nandu_eq403_cpu16_bench
#SBATCH --partition=bigmem
# CPU-scaling benchmark, Script-4-only re-run of earthquake/403 (New Madrid).
# Script 2/3/3_postprocess already completed for this scenario under
# conus_nandu_v1 (job 9471507, 12h24m @ 8 CPUs) -- damage/disruption data on
# disk is CPU-count-independent, so this skips straight to Script 4, same
# pattern as submit_earthquake_401_rerun.slurm.
#
# IMPORTANT -- before submitting this (and its cpu32/64/128 siblings): back
# up the CURRENTLY-REPORTED 403 output, since Script 4 writes to the same
# path regardless of CPU count and would otherwise overwrite the numbers
# already used in the finale figures:
#   mv /scratch/akothaw/multimodal_hazard_data/results/rerouting_analysis/conus_nandu_v1/403/1 \
#      /scratch/akothaw/multimodal_hazard_data/results/rerouting_analysis/conus_nandu_v1/403/1_baseline_8cpu_backup
# Submit the 4 benchmark jobs one at a time (or chained via --dependency=
# afterany:<jobid>), not concurrently -- they'd race on the same output path
# otherwise (the exact class of bug fixed in 8f8fa79/6a4768e this project).
# This job renames its own output to .../403/1_cpu16 on completion so the
# next one in the chain starts clean.
#
# num_of_chunk scaled proportionally to CPU count (20 chunks / 8 cpus = 2.5
# chunks/cpu, held constant) so higher core counts don't starve for chunks
# to work on. mem/DuckDB limit held IDENTICAL to the proven-working 8-CPU
# config (900G/800GB) -- CPU count is the only variable being tested here.
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=900G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_nandu_eq403_cpu16_bench_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_nandu_eq403_cpu16_bench_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=conus_nandu_v1
export RESIFLOW_RESULTS_VARIANT=conus_nandu_v1
export NIRD_DUCKDB_MEMORY_LIMIT=800GB
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_multihazard_nandu
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_HAZARD_TYPE=earthquake
export RESIFLOW_SCENARIO_PARAM=403

REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow
OUT=/scratch/akothaw/multimodal_hazard_data/results/rerouting_analysis/conus_nandu_v1/403/1

python $REPO/scripts/4_rerouting_and_recovery_scenario_loop.py 403 1 40 $SLURM_CPUS_PER_TASK

mv "$OUT" "${OUT}_cpu16"
