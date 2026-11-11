#!/bin/bash
#SBATCH --job-name=anvil_B_prune10_cpu64
#SBATCH --account=civ260045
#SBATCH --partition=shared
# Anvil experiment B: prune ratio 0.10 (instead of 0.01), 64 workers. Freight-only, full CONUS, streaming_arrays, 3 iteration(s).
# Tests: H7 does a coarser prune shorten the tail (delivered_frac_cum at iteration 3 vs 0.7727 baseline), H3 scaling point at 64 workers (per-phase rates), H4 memory at 64 workers, H2 hardware.
# Runtime factors (workers, memory, node type) do not change the numbers (proven on Hopper through iteration 3), so each run varies
# one algorithm setting AND one runtime setting at once; compare trajectories to the Hopper baseline, compare per-phase rates for runtime.
# ANVIL GOTCHAS: worker count is a LITERAL on the python line (a large --mem can inflate CPUs on shared); shared bills memory as a core
# fraction (~2 GB/core), so --mem=240G bills like ~120 cores/hour whatever --cpus-per-task is.
# --time=06:00:00 is a ceiling, not a prediction (Hopper streaming NumCpu=8: ~1.0-1.4 h per iteration).
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=64
#SBATCH --mem=240G
#SBATCH --output=/home/x-akothawala/multimodal_hazard_project/logs_anvil_B_prune10_cpu64_%j.out
#SBATCH --error=/home/x-akothawala/multimodal_hazard_project/logs_anvil_B_prune10_cpu64_%j.err
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

# Exactly 3 iteration(s): enough to see the signal and to compare with Stage 1's first iterations.
export RESIFLOW_MAX_FLOW_ITERATIONS=3
export NIRD_MAX_FLOW_ITERATIONS=3
export RESIFLOW_RESULTS_VARIANT=anvil_B_prune10_cpu64
export NIRD_RESULTS_VARIANT=anvil_B_prune10_cpu64
export NIRD_BASELINE_DB_PATH=/anvil/scratch/x-akothawala/multimodal_hazard_data/anvil_B_prune10_cpu64.duckdb

export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=100GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export NIRD_OD_ID_AT_INSERT=1
export NIRD_POOL_MAX_TASKS_PER_CHILD=50
export NIRD_LCP_COLLECT_POOL_RESULTS=0

export RESIFLOW_EDGE_PRUNE_RATIO=0.10
export RESIFLOW_LOG_CAPACITY_BLOCKED_EDGES=1
export NIRD_DUCKDB_TEMP_DIRECTORY=/anvil/scratch/x-akothawala/multimodal_hazard_data/duckdb_tmp_anvil_B_prune10_cpu64
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

# Log which resiflow actually got imported (must be under $CODE, not the shared checkout).
python -c "import resiflow; print('resiflow imported from:', resiflow.__file__)"

python $CODE/scripts/1_network_flow_model_revision.py 20 64
