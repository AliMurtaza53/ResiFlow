#!/bin/bash
#SBATCH --job-name=winter_storm_603
#SBATCH --partition=bigmem
# Full Script 2 -> 3 -> 3_postprocess -> 4 sequence for Winter Storm Elliott
# (603, hazard_subtype=winter_storm_elliott) against the CURRENT production
# results_variant (convergence_cpu8_bounded18) -- a second real winter-storm
# case study alongside Jonas (601); both stay runnable. Already a registered
# scenario with aligned data on disk (produced earlier via
# scripts/prepare_snodas_depth.py); this script has just never been
# submitted against the main production variant before -- a version exists
# under nandu_v1/submit_winter_storm_603.slurm, but that ran against a
# SEPARATE results_variant (conus_nandu_v1), not this one.
#
# --partition=bigmem, --path-realization=streaming_arrays: same reasoning as
# every other hazard job here -- damaged-edge count against the CONUS
# network under THIS results_variant is unmeasured (winter_storm's edge
# count is known to be large under other configs -- 11,556/483K in earlier
# Jonas runs -- so this is not a case to risk the normal partition on), and
# streaming_arrays is the validated-faster strategy for any brand-new job
# (see submit_cascadia_404.slurm's comment for the A/B test details).
#
# --time=24:00:00: not a measured requirement under this specific
# results_variant -- generous margin matching the other bigmem hazard jobs.
#SBATCH --time=24:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=900G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_winter_storm_603_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_winter_storm_603_%j.err
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
export RESIFLOW_HAZARD_TYPE=winter_storm
export RESIFLOW_WINTER_STORM_SUBTYPE=winter_storm_elliott
export RESIFLOW_SCENARIO_PARAM=603

REPO=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow
python $REPO/scripts/2_intersection_analysis.py 603 1
python $REPO/scripts/3_damage_analysis.py
python $REPO/scripts/3_postprocess_damage.py
python $REPO/scripts/4_rerouting_and_recovery_scenario_loop.py 603 1 20 $SLURM_CPUS_PER_TASK
