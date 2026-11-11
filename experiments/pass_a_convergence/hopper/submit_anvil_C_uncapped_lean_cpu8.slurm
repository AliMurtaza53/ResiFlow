#!/bin/bash
#SBATCH --job-name=anvil_C_uncapped_lean_cpu8
#SBATCH --account=civ260045
#SBATCH --partition=shared
# Anvil experiment C: capacity_scale=1000 (effectively uncapped) with a lean DuckDB limit, 8 workers, 1 iteration. Freight-only, full CONUS, streaming_arrays, 1 iteration(s).
# Tests: H6 is the tail capacity-driven (iteration 1 should deliver ~99.6%, only 0.36% is structurally unreachable), H8 can peak memory be cut with a 40GB DuckDB limit without slowing, H5 billing at a smaller --mem.
# Runtime factors (workers, memory, node type) do not change the numbers (proven on Hopper through iteration 3), so each run varies
# one algorithm setting AND one runtime setting at once; compare trajectories to the Hopper baseline, compare per-phase rates for runtime.
# ANVIL GOTCHAS: worker count is a LITERAL on the python line (a large --mem can inflate CPUs on shared); shared bills memory as a core
# fraction (~2 GB/core), so --mem=96G bills like ~48 cores/hour whatever --cpus-per-task is.
# --time=03:00:00 is a ceiling, not a prediction (Hopper streaming NumCpu=8: ~1.0-1.4 h per iteration).
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=96G
#SBATCH --output=/home/x-akothawala/multimodal_hazard_project/logs_anvil_C_uncapped_lean_cpu8_%j.out
#SBATCH --error=/home/x-akothawala/multimodal_hazard_project/logs_anvil_C_uncapped_lean_cpu8_%j.err
module purge
module load anaconda/2024.02-py311
source activate /anvil/scratch/x-akothawala/conda_envs/nird_v3

# The conda env has an EDITABLE install of resiflow pointing at the shared
# checkout (.../code/ResiFlow/src), which does not have the audit logging. Run
# from a separate checkout of feature/anaheim-assignment-diagnostics and put its
# src first on PYTHONPATH so it wins over the editable-install path.
CODE=/anvil/scratch/x-akothawala/multimodal_hazard_data/code/ResiFlow_anaheim
export PYTHONPATH=$CODE/src:$PYTHONPATH

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_anvil.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_anvil.json

# Freight only. Verify the .err contains "freight=... passenger=0" (or
# "Passenger OD not configured") before trusting the run.
export RESIFLOW_DISABLE_PASSENGER_OD=1
export NIRD_DISABLE_PASSENGER_OD=1

# Exactly 1 iteration(s): enough to see the signal and to compare with Stage 1's first iterations.
export RESIFLOW_MAX_FLOW_ITERATIONS=1
export NIRD_MAX_FLOW_ITERATIONS=1
export RESIFLOW_RESULTS_VARIANT=anvil_C_uncapped_lean_cpu8
export NIRD_RESULTS_VARIANT=anvil_C_uncapped_lean_cpu8
export NIRD_BASELINE_DB_PATH=/anvil/scratch/x-akothawala/multimodal_hazard_data/anvil_C_uncapped_lean_cpu8.duckdb

export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=40GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export NIRD_OD_ID_AT_INSERT=1
export NIRD_POOL_MAX_TASKS_PER_CHILD=50
export NIRD_LCP_COLLECT_POOL_RESULTS=0

export RESIFLOW_PARAM_OVERRIDES=/anvil/scratch/x-akothawala/multimodal_hazard_data/anvil_scripts/uncapped_overrides.json
export RESIFLOW_LOG_CAPACITY_BLOCKED_EDGES=1
export NIRD_DUCKDB_TEMP_DIRECTORY=/anvil/scratch/x-akothawala/multimodal_hazard_data/duckdb_tmp_anvil_C_uncapped_lean_cpu8
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

# Log which resiflow actually got imported (must be under $CODE, not the shared checkout).
python -c "import resiflow; print('resiflow imported from:', resiflow.__file__)"

python $CODE/scripts/1_network_flow_model_revision.py 20 8
