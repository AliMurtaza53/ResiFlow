#!/bin/bash
#SBATCH --job-name=hazard_convergence_cpu8_bounded18
#SBATCH --partition=normal
# Bounded Pass A baseline for the VA multi-hazard advisor comparison --
# RESIFLOW_MAX_FLOW_ITERATIONS=18 hard-caps the loop instead of waiting for
# NIRD_STAGNANT_ITERATIONS-based convergence (submit_cpu8_convergence.slurm's
# unbounded mode). The earlier unbounded convergence_cpu8 run never finished
# within its 30h budget and had to be killed -- recover_convergence_output.py
# recovered raw OD-path data from it, but that recovery is explicitly NOT a
# substitute for the official edge_flows.gpq (no road geometry, no
# iteration-by-iteration capacity/speed state -- see that script's own
# docstring). A bounded run is far more likely to actually finish cleanly and
# produce a real, usable baseline. 18 is the midpoint of the user's chosen
# 15-20 range; see docs/ORC_HOPPER_SETUP.md and this session's plan
# (precious-gathering-quail.md) for the "bounded vs. stagnation-based"
# tradeoff discussion.
#
# Time budget: same pessimistic per-iteration estimate as
# submit_cpu8_convergence.slurm (83.5min/iter, iteration 1, job 9000424,
# 2026-07-21) -- 18 iterations x 83.5min = ~25h. Budgeting 30h for headroom,
# same as the unbounded run, since remain_od shrinking each iteration likely
# makes this pessimistic anyway.
#SBATCH --time=30:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_cpu8_bounded18_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_cpu8_bounded18_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

export RESIFLOW_MAX_FLOW_ITERATIONS=18
export NIRD_MAX_FLOW_ITERATIONS=18

# Distinct name from the dead convergence_cpu8/convergence_cpu8_recovered --
# this is a fresh run, not a continuation of either.
export RESIFLOW_RESULTS_VARIANT=convergence_cpu8_bounded18
export NIRD_RESULTS_VARIANT=convergence_cpu8_bounded18
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/convergence_cpu8_bounded18.duckdb

# Goal 15 validated fixes -- keep these regardless of core count
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=100GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact

export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_cpu8_bounded18
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
