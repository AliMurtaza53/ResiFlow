#!/bin/bash
#SBATCH --job-name=nandu_winter_storm_601
#SBATCH --partition=bigmem
# Full Script 2 -> 3 -> 3_postprocess -> 4 for winter storm (601, Winter
# Storm Jonas SNODAS) against the conus_nandu_v1 baseline. Raw SNODAS raster
# already aligned under soge_clusters/inputs/va_multihazard_aligned/ (shared
# across results_variants). bigmem: winter_storm's real damaged-edge count
# (11,556 of 483K CONUS edges) needs bigmem even with the edge-index sort
# fix in place -- see docs/VA_MULTIHAZARD_COMPARISON.md, "Resolved: Stage 2
# row explosion for widespread hazards". Must run AFTER
# submit_cpu8_nandu_v1.slurm (Pass A) completes.
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=900G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_nandu_winter_storm_601_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_nandu_winter_storm_601_%j.err
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
export RESIFLOW_SCENARIO_PARAM=601

REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow
python $REPO/scripts/2_intersection_analysis.py 601 1
python $REPO/scripts/3_damage_analysis.py
python $REPO/scripts/3_postprocess_damage.py
python $REPO/scripts/4_rerouting_and_recovery_scenario_loop.py 601 1 20 $SLURM_CPUS_PER_TASK
