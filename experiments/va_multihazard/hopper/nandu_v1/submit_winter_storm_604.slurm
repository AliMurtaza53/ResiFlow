#!/bin/bash
#SBATCH --job-name=nandu_winter_storm_604
#SBATCH --partition=bigmem
# Full Script 2 -> 3 -> 3_postprocess -> 4 for winter storm (604,
# "Snowmageddon" SNODAS, full CONUS extent) against the conus_nandu_v1
# baseline. Raw SNODAS raster already aligned under
# soge_clusters/inputs/va_multihazard_aligned/winter_storm_snowmageddon/
# (shared across results_variants). bigmem: mirrors 601's settings as a
# safety margin -- see docs/VA_MULTIHAZARD_COMPARISON.md, "Resolved: Stage 2
# row explosion for widespread hazards". Must run AFTER
# submit_cpu8_nandu_v1.slurm (Pass A) AND submit_build_edge_index.slurm
# complete.
# --time bumped 48h -> 96h (2026-08-28): job 9471510 was still deep in
# Script 4 (DuckDB chunked-compact aggregation, ~1/20 chunks per recovery
# day x 6 days) at 47h48m with no checkpoint/resume capability -- a SLURM
# TimeLimit extension on a running job requires operator/admin privileges
# regular users don't have (confirmed: `scontrol update ... TimeLimit=`
# returned "Access/permission denied"), so the budget has to be sized
# generously up front rather than extended live. bigmem allows up to 7 days.
#SBATCH --time=96:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=900G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_nandu_winter_storm_604_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_nandu_winter_storm_604_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=conus_nandu_v1
export RESIFLOW_RESULTS_VARIANT=conus_nandu_v1
export NIRD_DUCKDB_MEMORY_LIMIT=800GB
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_va_multihazard_nandu
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_HAZARD_TYPE=winter_storm
export RESIFLOW_SCENARIO_PARAM=604

REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow
python $REPO/scripts/2_intersection_analysis.py 604 1
python $REPO/scripts/3_damage_analysis.py
python $REPO/scripts/3_postprocess_damage.py
python $REPO/scripts/4_rerouting_and_recovery_scenario_loop.py 604 1 20 $SLURM_CPUS_PER_TASK
