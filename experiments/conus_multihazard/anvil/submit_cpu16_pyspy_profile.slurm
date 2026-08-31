#!/bin/bash
#SBATCH --job-name=anvil_pyspy_profile
#SBATCH --account=civ260045
#SBATCH --partition=shared
# Sampling-profiler run to find the REAL cause of realize_paths_streaming()'s
# per-chunk slowdown at CONUS scale (docs/PROJECT_LOG.md, "Investigated:
# realize_paths_streaming() per-chunk slowdown..." entry, 2026-08-30) -- two
# plausible-looking hypotheses (LIMIT/OFFSET rescanning, np.add.at overhead)
# were both disproven by local isolated testing, so the dominant cost (most
# of the ~60 real minutes pass 1 takes) remains unexplained by anything
# reproducible off-cluster. This attaches py-spy (a sampling profiler that
# reads the live Python call stack via ptrace, no code changes needed) to a
# real Anvil run to see where the process is ACTUALLY spending time --
# likely candidates going in: DuckDB internals (memory/spill under the large
# NIRD_DUCKDB_MEMORY_LIMIT), Arrow<->pandas conversion, or filesystem I/O on
# Anvil's shared scratch, none of which a local microbenchmark can see.
#
# Same cpu16 config as the already-completed, known-good
# submit_cpu16_scale_test.slurm (job 20240812, COMPLETED, 5049.9s total) --
# reusing a config we already know runs correctly end-to-end, just with
# py-spy attached, so any profiling overhead's effect on wall time is
# measurable against that baseline.
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=16
#SBATCH --mem=120G
#SBATCH --output=/home/x-akothawala/multimodal_hazard_project/logs_anvil_pyspy_profile_%j.out
#SBATCH --error=/home/x-akothawala/multimodal_hazard_project/logs_anvil_pyspy_profile_%j.err

module purge
module load anaconda/2024.02-py311
source activate /anvil/scratch/x-akothawala/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_anvil.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_anvil.json

export RESIFLOW_MAX_FLOW_ITERATIONS=1
export NIRD_MAX_FLOW_ITERATIONS=1

export RESIFLOW_RESULTS_VARIANT=anvil_pyspy_profile_cpu16
export NIRD_RESULTS_VARIANT=anvil_pyspy_profile_cpu16
export NIRD_BASELINE_DB_PATH=/anvil/scratch/x-akothawala/multimodal_hazard_data/anvil_pyspy_profile_cpu16.duckdb

export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=90GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export NIRD_DUCKDB_TEMP_DIRECTORY=/anvil/scratch/x-akothawala/multimodal_hazard_data/duckdb_tmp_pyspy_cpu16
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

REPO=/anvil/scratch/x-akothawala/multimodal_hazard_data/code/ResiFlow
STDOUT_LOG=$HOME/multimodal_hazard_project/pyspy_run_stdout.log
STDERR_LOG=$HOME/multimodal_hazard_project/pyspy_run_stderr.log
PROFILE_OUT=$HOME/multimodal_hazard_project/pyspy_cpu16_streaming.speedscope.json

# Launch the real workload in the background so we can attach py-spy to it
# by PID once it reaches the phase we actually want to profile (no point
# spending profiler samples on the LCP-dispatch pool, which is already
# understood and separately benchmarked).
python $REPO/scripts/1_network_flow_model_revision.py 20 16 \
    > "$STDOUT_LOG" 2> "$STDERR_LOG" &
MAIN_PID=$!
echo "Main workload PID: $MAIN_PID"

# Poll for the phase-start marker instead of guessing a sleep duration.
echo "Waiting for 'Streaming realization pass 1' to appear in the log..."
while ! grep -q "Streaming realization pass 1" "$STDERR_LOG" 2>/dev/null; do
    if ! kill -0 "$MAIN_PID" 2>/dev/null; then
        echo "Main process exited before reaching the streaming phase -- aborting profile."
        wait "$MAIN_PID"
        exit 1
    fi
    sleep 5
done
echo "Streaming phase detected at $(date). Attaching py-spy (native, speedscope format)..."

# --duration 6600 (110min): generous upper bound covering both realization
# passes end-to-end (pass 1 alone took 60.6min in the non-profiled run,
# job 20240809/cpu64_v2) -- py-spy stops on its own if the target process
# exits first, so this is a ceiling, not a fixed wait.
py-spy record \
    --pid "$MAIN_PID" \
    --native \
    --rate 100 \
    --duration 6600 \
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
