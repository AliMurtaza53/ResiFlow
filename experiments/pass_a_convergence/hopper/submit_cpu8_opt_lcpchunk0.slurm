#!/bin/bash
#SBATCH --job-name=hazard_opt_lcpchunk0
#SBATCH --partition=normal
# Optimization experiment 5 of 5 (see docs/ORC_HOPPER_SETUP.md "Optimization
# experiments" section). Isolates ONE variable against the cpu8 baseline
# (job 9000424, 2026-07-21): NIRD_LCP_DEST_CHUNK_SIZE=0, which DISABLES
# per-origin destination chunking entirely (each origin becomes exactly
# one task, matching the origin count -- 3143 tasks instead of 34374). This
# is the aggressive bookend to opt_lcpchunk1000: maximum reduction in
# redundant Dijkstra tree recomputation, but also the highest per-task
# memory risk, since a single task/result now holds ALL of one origin's
# ~3081 average destinations (worst-case origins likely have far more).
# The Goal 15 notes (docs/ORC_HOPPER_SETUP.md) record ~45GB RSS from
# unchunked dispatch at a *smaller* 5M-OD run with ~1680 destinations for
# the single largest origin -- this run's largest origin could exceed
# that. RSS checkpoint [iter1_lcp_pool_done] is the number that matters
# here; if it spikes uncomfortably close to the 128G ceiling (unlike
# baseline's ~24GB), that tells us disabling chunking outright isn't
# viable at this OD scale and 1000 (or something between 300 and 1000)
# is the real ceiling -- treat this run as informational even if it
# doesn't complete cleanly.
#SBATCH --time=04:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_cpu8_opt_lcpchunk0_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_cpu8_opt_lcpchunk0_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

# One iteration only -- this is a timing experiment, not a convergence run.
export RESIFLOW_MAX_FLOW_ITERATIONS=1
export NIRD_MAX_FLOW_ITERATIONS=1

# Distinct output/db path so this doesn't collide with other runs.
export RESIFLOW_RESULTS_VARIANT=opt_lcpchunk0_cpu8
export NIRD_RESULTS_VARIANT=opt_lcpchunk0_cpu8
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/opt_lcpchunk0_cpu8.duckdb

export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=100GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_opt_lcpchunk0

# THE VARIABLE UNDER TEST -- 0 (disabled) instead of the baseline's 300.
export NIRD_LCP_DEST_CHUNK_SIZE=0

export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
