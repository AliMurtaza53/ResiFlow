#!/bin/bash
#SBATCH --job-name=anvil_od_id_test
#SBATCH --account=civ260045
#SBATCH --partition=shared
# Validates NIRD_OD_ID_AT_INSERT=1 ("Patch 6") at real CONUS scale -- a
# previously-benchmarked fix (notes/perf_findings/GOAL3_FIX_AND_BENCHMARK.md,
# 2026-07-12, branch perf/pass-a-convergence-diagnosis) that removed ~1188s
# of "od_id assignment" phase time in that earlier context, but was never
# actually set in any current production or benchmark SLURM script -- our
# own cpu16/32/64 runs this session all paid the slow default path (179.6s
# in job 20243490's profiled run) without knowing a validated opt-out
# existed. Mechanism: assigns od_id incrementally as LCP results are
# inserted, instead of a separate CREATE TABLE AS SELECT ROW_NUMBER() OVER
# (ORDER BY origin, destination) rewrite of the whole ~9.68M-row table
# (including its large `path` list column) afterward. od_id only needs to
# be a stable unique join key downstream -- nothing depends on it being
# sorted by (origin, destination) -- so this changes performance, not
# results; this run's cost totals should match job 20240812/20243490's
# exactly, same as the base config otherwise.
#
# Same cpu16 config as the completed, fixed-realize_paths_streaming run
# (job 20243490, 1336.4s total) -- only NIRD_OD_ID_AT_INSERT added.
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=120G
#SBATCH --output=/home/x-akothawala/multimodal_hazard_project/logs_anvil_od_id_test_%j.out
#SBATCH --error=/home/x-akothawala/multimodal_hazard_project/logs_anvil_od_id_test_%j.err

module purge
module load anaconda/2024.02-py311
source activate /anvil/scratch/x-akothawala/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_anvil.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_anvil.json

# One iteration only -- this is a scaling comparison test, not a convergence run.
export RESIFLOW_MAX_FLOW_ITERATIONS=1
export NIRD_MAX_FLOW_ITERATIONS=1

export RESIFLOW_RESULTS_VARIANT=anvil_od_id_test_cpu16
export NIRD_RESULTS_VARIANT=anvil_od_id_test_cpu16
export NIRD_BASELINE_DB_PATH=/anvil/scratch/x-akothawala/multimodal_hazard_data/anvil_od_id_test_cpu16.duckdb

export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=90GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export NIRD_OD_ID_AT_INSERT=1
export NIRD_DUCKDB_TEMP_DIRECTORY=/anvil/scratch/x-akothawala/multimodal_hazard_data/duckdb_tmp_od_id_test
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

# Literal 16, not $SLURM_CPUS_PER_TASK -- see submit_cpu16_scale_test.slurm's
# comment for why (Anvil's shared partition inflates the granted allocation
# based on --mem, and that env var reflects the inflated value).
REPO=/anvil/scratch/x-akothawala/multimodal_hazard_data/code/ResiFlow
python $REPO/scripts/1_network_flow_model_revision.py 20 16
