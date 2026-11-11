#!/bin/bash
#SBATCH --job-name=stage2_chunked_cpu2
#SBATCH --partition=normal
# Stage 2 runtime-config probe: duckdb_chunked_compact, NumCpu=2, freight-only, full CONUS, EXACTLY 2 iterations.
# Control = the first two iterations of Stage 1 (job 3666243: duckdb_chunked_compact, NumCpu=1). Compare per-iteration
# ITER_AUDIT delivered/isolated/remain flow (must match the control within tolerance: Lesson 2), iter_wall_s, and peak RSS.
# --time is a CEILING, not a prediction. Measured anchor (Stage 1, NumCpu=1): shortest-path phase of iteration 1 took
# ~49 min (26.17% of 12,496 tasks in 12.9 min). Path realization time is not yet measured, so 12 h covers 2 iterations
# with wide margin. Revise from Stage 1 iter_wall_s if these runs are repeated.
#SBATCH --time=12:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=175G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_stage2_chunked_cpu2_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_stage2_chunked_cpu2_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

# The conda env has an EDITABLE install of resiflow pointing at the shared
# checkout (.../code/ResiFlow/src), which does not have the audit logging. Run
# from a separate checkout of feature/anaheim-assignment-diagnostics and put its
# src first on PYTHONPATH so it wins over the editable-install path.
CODE=/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_stage1
export PYTHONPATH=$CODE/src:$PYTHONPATH

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

# Freight only. Verify the .err contains "freight=... passenger=0" (or
# "Passenger OD not configured") before trusting the run.
export RESIFLOW_DISABLE_PASSENGER_OD=1
export NIRD_DISABLE_PASSENGER_OD=1

# Exactly 2 iterations (probe), so the result is comparable with Stage 1's first two iterations.
export RESIFLOW_MAX_FLOW_ITERATIONS=2
export NIRD_MAX_FLOW_ITERATIONS=2
export RESIFLOW_RESULTS_VARIANT=stage2_chunked_cpu2
export NIRD_RESULTS_VARIANT=stage2_chunked_cpu2
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/stage2_chunked_cpu2.duckdb

export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=100GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact

export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_stage2_chunked_cpu2
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

# Log which resiflow actually got imported (must be under $CODE, not the shared checkout).
python -c "import resiflow; print('resiflow imported from:', resiflow.__file__)"

python $CODE/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
