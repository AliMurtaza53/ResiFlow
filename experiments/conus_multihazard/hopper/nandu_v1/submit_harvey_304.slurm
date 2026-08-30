#!/bin/bash
#SBATCH --job-name=nandu_harvey_304
#SBATCH --partition=bigmem
# Full Script 2 -> 3 -> 3_postprocess -> 4 for Hurricane Harvey (304, the
# paper's actual flood case study) against the conus_nandu_v1 baseline.
# Raw depth raster already prepared under soge_clusters/inputs/
# multihazard_aligned/flood_harvey_houston/ (shared across
# results_variants) -- see submit_harvey_prep.slurm, already run once.
# bigmem: matches the resourcing the first Harvey run against
# convergence_cpu8_bounded18 used (1,812 damaged edges, real number now
# known). Must run AFTER submit_cpu8_nandu_v1.slurm (Pass A) completes.
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=900G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_nandu_harvey_304_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_nandu_harvey_304_%j.err
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
export RESIFLOW_HAZARD_TYPE=flood
export RESIFLOW_FLOOD_SUBTYPE=flood_harvey_houston
export RESIFLOW_SCENARIO_PARAM=304

REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow
python $REPO/scripts/2_intersection_analysis.py 304 1
python $REPO/scripts/3_damage_analysis.py
python $REPO/scripts/3_postprocess_damage.py
python $REPO/scripts/4_rerouting_and_recovery_scenario_loop.py 304 1 20 $SLURM_CPUS_PER_TASK
