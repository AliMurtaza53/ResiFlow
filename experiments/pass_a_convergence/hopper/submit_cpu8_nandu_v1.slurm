#!/bin/bash
#SBATCH --job-name=hazard_convergence_nandu_v1
#SBATCH --partition=normal
# Pass A baseline for the feature/conus-nandu-params branch -- iteration 1 of
# the "full CONUS run using Nandu's updated parameters" project. A NEW,
# separate results_variant (conus_nandu_v1) from convergence_cpu8_bounded18,
# so the current 4-hazard advisor comparison stays untouched and available
# throughout this run.
#
# Why Pass A needs re-running, not just Scripts 2-4: this branch changes
# VOT ($18.50->$21.80 car, $32.50->$37.20 truck), car occupancy (1.06->1.67),
# and fuel costs -- all of which feed the generalised cost function that
# drives route choice during flow assignment, not just the reported dollar
# totals. A stale Pass A baseline (old VOT) would silently mismatch the new
# Script 2-4 cost accounting.
#
# 18 iterations, same bounded-convergence choice as convergence_cpu8_bounded18
# (see that script's own comments for the "bounded vs. stagnation-based"
# tradeoff) -- this is iteration 1 of an explicitly iterative project, not
# the final unbounded run (that's still the Anvil plan, separately).
#
# --mem=160G / NIRD_DUCKDB_MEMORY_LIMIT=130GB: the corrected pairing
# (confirmed via `sinfo`/`scontrol` this project: normal-partition nodes
# have 180GB physical RAM, not 128GB) -- bounded18's original 128G/100GB
# was an under-provisioned carry-over from before that was confirmed; no
# reason to repeat the under-provisioning on a fresh baseline.
#SBATCH --time=30:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=160G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_cpu8_nandu_v1_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_cpu8_nandu_v1_%j.err
#SBATCH --exclude=hop059

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

export RESIFLOW_MAX_FLOW_ITERATIONS=18
export NIRD_MAX_FLOW_ITERATIONS=18

export RESIFLOW_RESULTS_VARIANT=conus_nandu_v1
export NIRD_RESULTS_VARIANT=conus_nandu_v1
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/conus_nandu_v1.duckdb

# Goal 15 validated fixes -- keep these regardless of core count
export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=130GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact

export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_cpu8_nandu_v1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
