#!/bin/bash
#SBATCH --job-name=harvey_304
#SBATCH --partition=bigmem
# Full Script 2 -> 3 -> 3_postprocess -> 4 sequence for Hurricane Harvey
# (304, hazard_subtype=flood_harvey_houston) -- the paper's actual flood
# hazard (Section 4.1/Table 2), NOT the VA flood (301) this project also
# has. Never run before on any cluster -- run submit_harvey_prep.slurm
# first and confirm its output exists before submitting this.
#
# --partition=bigmem, defensively: Harvey's damaged-edge count against the
# CONUS network is genuinely UNKNOWN (never run). Houston/Harris County is a
# real flood-prone metro, so this could plausibly land anywhere from a
# handful of edges (like VA flood's single closure) to a winter_storm-sized
# widespread footprint (11,556 edges) depending on how much of Harvey's
# depth grid falls on FAF5 strategic-network segments. Same reasoning
# submit_landslide_501.slurm used -- bigmem from the start avoids repeating
# the OOM-and-retry cycle already paid for winter_storm and (partially)
# landslide.
#
# --time=24:00:00: same generous margin as landslide/winter_storm's bigmem
# jobs -- not a measured requirement for this specific hazard.
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=900G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_harvey_304_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_harvey_304_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_RESULTS_VARIANT=convergence_cpu8_bounded18
export RESIFLOW_RESULTS_VARIANT=convergence_cpu8_bounded18
export NIRD_DUCKDB_MEMORY_LIMIT=800GB
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_multihazard
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
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
