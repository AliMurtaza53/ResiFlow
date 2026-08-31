#!/bin/bash
#SBATCH --job-name=anvil_pyspy_fullrun
#SBATCH --account=civ260045
#SBATCH --partition=shared
# Full-run py-spy profile, START TO FINISH -- the earlier profiling job
# (submit_cpu16_pyspy_profile.slurm, job 20243490) only attached once
# "Streaming realization pass 1" appeared in the log, deliberately skipping
# the LCP-dispatch pool phase because that phase was "already understood
# and separately benchmarked". That benchmarking (16/32/64 CPU-scaling
# comparison) found weak, non-monotonic scaling (16=740s, 32=757s, 64=701s)
# that was never actually explained -- and now that the realize_paths_
# streaming fix (docs/PROJECT_LOG.md, 2026-08-30) cut total Pass A wall time
# from 84.2min to 22.3min, LCP dispatch is ~52% of what's left (696s of
# 1336s) -- the single largest remaining phase, and the only one with no
# profile at all. This run profiles the whole process from launch.
#
# Same cpu16 config as job 20243490 (COMPLETED, 1336.4s total with the fix)
# -- distinct results-variant/output paths so this doesn't collide with it.
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=120G
#SBATCH --output=/home/x-akothawala/multimodal_hazard_project/logs_anvil_pyspy_fullrun_%j.out
#SBATCH --error=/home/x-akothawala/multimodal_hazard_project/logs_anvil_pyspy_fullrun_%j.err

module purge
module load anaconda/2024.02-py311
source activate /anvil/scratch/x-akothawala/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_anvil.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_anvil.json

export RESIFLOW_MAX_FLOW_ITERATIONS=1
export NIRD_MAX_FLOW_ITERATIONS=1

export RESIFLOW_RESULTS_VARIANT=anvil_pyspy_fullrun_cpu16
export NIRD_RESULTS_VARIANT=anvil_pyspy_fullrun_cpu16
export NIRD_BASELINE_DB_PATH=/anvil/scratch/x-akothawala/multimodal_hazard_data/anvil_pyspy_fullrun_cpu16.duckdb

export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=90GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export NIRD_DUCKDB_TEMP_DIRECTORY=/anvil/scratch/x-akothawala/multimodal_hazard_data/duckdb_tmp_pyspy_fullrun
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

REPO=/anvil/scratch/x-akothawala/multimodal_hazard_data/code/ResiFlow
STDOUT_LOG=$HOME/multimodal_hazard_project/pyspy_fullrun_stdout.log
STDERR_LOG=$HOME/multimodal_hazard_project/pyspy_fullrun_stderr.log
PROFILE_OUT=$HOME/multimodal_hazard_project/pyspy_cpu16_fullrun.speedscope.json

python $REPO/scripts/1_network_flow_model_revision.py 20 16 \
    > "$STDOUT_LOG" 2> "$STDERR_LOG" &
MAIN_PID=$!
echo "Main workload PID: $MAIN_PID at $(date)"

# Attach immediately -- no phase to wait for this time. --duration 1800
# (30min) comfortably covers the whole ~22min run with margin; py-spy stops
# on its own when the target process exits.
py-spy record \
    --pid "$MAIN_PID" \
    --native \
    --rate 100 \
    --duration 1800 \
    --format speedscope \
    --output "$PROFILE_OUT" &
PYSPY_PID=$!

wait "$MAIN_PID"
MAIN_EXIT=$?
echo "Main workload exited with code $MAIN_EXIT at $(date)."

wait "$PYSPY_PID" 2>/dev/null
echo "py-spy finished. Profile written to $PROFILE_OUT"
ls -la "$PROFILE_OUT"

exit $MAIN_EXIT
