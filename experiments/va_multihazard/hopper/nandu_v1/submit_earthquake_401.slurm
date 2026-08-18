#!/bin/bash
#SBATCH --job-name=nandu_earthquake_401
#SBATCH --partition=normal
# Full Script 2 -> 3 -> 3_postprocess -> 4 for earthquake (401, Mineral VA
# ShakeMap) against the conus_nandu_v1 baseline. Raw ShakeMap PGA raster is
# already aligned under soge_clusters/inputs/va_multihazard_aligned/ (shared
# across results_variants) -- only re-runs the variant-dependent steps.
# Must run AFTER submit_cpu8_nandu_v1.slurm (Pass A) completes.
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=160G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_nandu_earthquake_401_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_nandu_earthquake_401_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=conus_nandu_v1
export RESIFLOW_RESULTS_VARIANT=conus_nandu_v1
export NIRD_DUCKDB_MEMORY_LIMIT=130GB
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_va_multihazard_nandu
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_HAZARD_TYPE=earthquake
export RESIFLOW_SCENARIO_PARAM=401

REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow
python $REPO/scripts/2_intersection_analysis.py 401 1
python $REPO/scripts/3_damage_analysis.py
python $REPO/scripts/3_postprocess_damage.py
python $REPO/scripts/4_rerouting_and_recovery_scenario_loop.py 401 1 20 $SLURM_CPUS_PER_TASK
