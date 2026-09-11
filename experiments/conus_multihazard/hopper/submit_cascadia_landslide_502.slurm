#!/bin/bash
#SBATCH --job-name=cascadia_landslide_502
#SBATCH --partition=bigmem
# Full Script 2 -> 3 -> 3_postprocess -> 4 sequence for the co-seismic
# landslide paired with the Cascadia M9 earthquake (502,
# hazard_subtype=landslide_cascadia_m9) -- a second real-landslide case
# study alongside the Mineral-paired one (501, hazard_subtype=landslide);
# both stay runnable. Never run before on any cluster -- run
# submit_cascadia_prep.slurm first and confirm its output exists before
# submitting this. Independent of submit_cascadia_404.slurm (different
# scenario_param, different output path) -- can run in parallel with it.
#
# --partition=bigmem, --path-realization=streaming_arrays: same reasoning as
# submit_cascadia_404.slurm -- see that script's comments.
#
# --time=24:00:00: not a measured requirement -- generous margin matching
# the other bigmem hazard jobs.
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=900G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_cascadia_landslide_502_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_cascadia_landslide_502_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=convergence_cpu8_bounded18
export RESIFLOW_RESULTS_VARIANT=convergence_cpu8_bounded18
export NIRD_DUCKDB_MEMORY_LIMIT=800GB
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_multihazard
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export RESIFLOW_HAZARD_TYPE=landslide
export RESIFLOW_LANDSLIDE_SUBTYPE=landslide_cascadia_m9
export RESIFLOW_SCENARIO_PARAM=502

REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow
python $REPO/scripts/2_intersection_analysis.py 502 1
python $REPO/scripts/3_damage_analysis.py
python $REPO/scripts/3_postprocess_damage.py
python $REPO/scripts/4_rerouting_and_recovery_scenario_loop.py 502 1 20 $SLURM_CPUS_PER_TASK
