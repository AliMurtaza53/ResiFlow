#!/bin/bash
#SBATCH --job-name=anvil_streaming_cpu128
#SBATCH --account=civ260045
#SBATCH --partition=shared
# Anvil NumCpu-scaling probe: streaming_arrays, NumCpu=128, freight-only, full CONUS, EXACTLY 2 iterations.
# Same inputs (byte-identical network links and freight OD, md5-verified against Hopper) and same code branch as the Hopper
# Stage 2 probes, so delivered/isolated/remain flow must match Hopper's to every printed digit (Lesson 2); only timing differs.
# ANVIL GOTCHAS (docs/ANVIL_SETUP.md): (1) the worker count is a LITERAL on the python line, never $SLURM_CPUS_PER_TASK, because a
# large --mem makes the shared partition grant more CPUs than requested; (2) shared bills memory as a core fraction (~2 GB/core),
# so --mem=240G bills like ~120 cores per hour whatever --cpus-per-task is.
# --mem: Hopper streaming NumCpu=8 peaked at 114.6 GB; worker-count effect on memory at 128 workers is unmeasured, so margin is kept.
# --time=06:00:00 is a ceiling, not a prediction (Hopper streaming NumCpu=8, 2 iterations: 2h51m total). Worst-case SU = ceiling x billed cores.
#SBATCH --time=06:00:00
#SBATCH --cpus-per-task=128
#SBATCH --mem=240G
#SBATCH --output=/home/x-akothawala/multimodal_hazard_project/logs_anvil_streaming_cpu128_%j.out
#SBATCH --error=/home/x-akothawala/multimodal_hazard_project/logs_anvil_streaming_cpu128_%j.err

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

# Exactly 2 iterations (probe), so the result is comparable with Stage 1's first two iterations.
export RESIFLOW_MAX_FLOW_ITERATIONS=2
export NIRD_MAX_FLOW_ITERATIONS=2
export RESIFLOW_RESULTS_VARIANT=anvil_streaming_cpu128
export NIRD_RESULTS_VARIANT=anvil_streaming_cpu128
export NIRD_BASELINE_DB_PATH=/anvil/scratch/x-akothawala/multimodal_hazard_data/anvil_streaming_cpu128.duckdb

export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=100GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export NIRD_OD_ID_AT_INSERT=1
export NIRD_POOL_MAX_TASKS_PER_CHILD=50
export NIRD_LCP_COLLECT_POOL_RESULTS=0

export NIRD_DUCKDB_TEMP_DIRECTORY=/anvil/scratch/x-akothawala/multimodal_hazard_data/duckdb_tmp_anvil_streaming_cpu128
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

# Log which resiflow actually got imported (must be under $CODE, not the shared checkout).
python -c "import resiflow; print('resiflow imported from:', resiflow.__file__)"

python $CODE/scripts/1_network_flow_model_revision.py 20 128
