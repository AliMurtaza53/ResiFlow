#!/bin/bash
#SBATCH --job-name=anvil_gc_disable_test
#SBATCH --account=civ260045
#SBATCH --partition=shared
# Validates NIRD_LCP_GC_DISABLE=1 -- a new opt-in flag added after a
# full-run py-spy profile (Anvil, 2026-08-30, job 20244142) found
# gc_collect_main as the single largest self-time hotspot during LCP
# dispatch, ahead of any DuckDB or numpy frame, with sched_yield and the
# pickle module (imap_unordered IPC deserialization) close behind. Matches
# an earlier, still-unresolved finding (docs/PROJECT_LOG.md "Performance
# findings" #1): multiprocessing pool/pickle/IPC overhead dominating over
# actual per-task work -- likely explanation for LCP dispatch's weak,
# non-monotonic CPU-scaling (16=740s, 32=757s, 64=701s on Anvil).
#
# Same cpu16 config as job 20243490 (COMPLETED, 1336.4s total, 695.8s LCP
# dispatch) -- only NIRD_LCP_GC_DISABLE added. Watch RSS checkpoints in the
# log closely: disabling cyclic GC is only safe if nothing in the
# multiprocessing/pickle path creates reference cycles (a real risk, not
# just a theoretical one) -- this run's RSS trend vs. the baseline's is the
# actual safety check, not just the timing.
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=120G
#SBATCH --output=/home/x-akothawala/multimodal_hazard_project/logs_anvil_gc_disable_test_%j.out
#SBATCH --error=/home/x-akothawala/multimodal_hazard_project/logs_anvil_gc_disable_test_%j.err

module purge
module load anaconda/2024.02-py311
source activate /anvil/scratch/x-akothawala/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_anvil.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_anvil.json

# One iteration only -- this is a scaling comparison test, not a convergence run.
export RESIFLOW_MAX_FLOW_ITERATIONS=1
export NIRD_MAX_FLOW_ITERATIONS=1

export RESIFLOW_RESULTS_VARIANT=anvil_gc_disable_test_cpu16
export NIRD_RESULTS_VARIANT=anvil_gc_disable_test_cpu16
export NIRD_BASELINE_DB_PATH=/anvil/scratch/x-akothawala/multimodal_hazard_data/anvil_gc_disable_test_cpu16.duckdb

export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=90GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export NIRD_LCP_GC_DISABLE=1
export NIRD_DUCKDB_TEMP_DIRECTORY=/anvil/scratch/x-akothawala/multimodal_hazard_data/duckdb_tmp_gc_disable_test
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

# Literal 16, not $SLURM_CPUS_PER_TASK -- see submit_cpu16_scale_test.slurm's
# comment for why (Anvil's shared partition inflates the granted allocation
# based on --mem, and that env var reflects the inflated value).
REPO=/anvil/scratch/x-akothawala/multimodal_hazard_data/code/ResiFlow
python $REPO/scripts/1_network_flow_model_revision.py 20 16
