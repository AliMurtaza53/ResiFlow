#!/bin/bash
#SBATCH --job-name=stage1_freight_only
#SBATCH --partition=normal
# Stage 1 control: freight-only, full CONUS network, NumCpu=1, audit logging on
# (ITER_AUDIT / INVARIANT lines, default-on in this branch), unbounded
# iterations with the existing stagnation guard (stop rule unchanged).
#
# Config deliberately mirrors the proven full-scale Pass A runs
# (submit_cpu8_bounded18.slurm / oct12): duckdb_chunked_compact, same chunk and
# memory settings. The ONLY intended differences are (a) passenger OD disabled,
# (b) NumCpu=1, (c) iterations unbounded. The Stage 2 strategy comparison
# (streaming_arrays vs duckdb_chunked_compact) comes later; streaming_arrays has
# no full-scale many-iteration record, so it is not used for the control.
#
# --time: UNMEASURED for this configuration, so it is set to the partition
# ceiling (7 days, the "normal" partition limit) on purpose. This run's job is to
# measure the per-iteration rate. Only anchor: iteration 1 of the freight+passenger
# cpu8 test took 83.5 min (job 9000424); freight is ~1% of that demand but
# NumCpu=1 vs 8 is unmeasured. Read iter_wall_s from the first ITER_AUDIT lines
# and scancel/resubmit with a measured limit if needed. A prior unbounded run
# (convergence_cpu8) was killed at its wall limit, so the per-iteration audit
# lines (which survive a kill) are the product that matters here.
#SBATCH --time=7-00:00:00
#SBATCH --cpus-per-task=1
#SBATCH --mem=128G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_stage1_freight_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_stage1_freight_%j.err

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

# Unbounded: leave RESIFLOW_MAX_FLOW_ITERATIONS unset. Stagnation guard default.
export RESIFLOW_RESULTS_VARIANT=stage1_freight_only_cpu1
export NIRD_RESULTS_VARIANT=stage1_freight_only_cpu1
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/stage1_freight_only_cpu1.duckdb

export NIRD_LCP_DEST_CHUNK_SIZE=1000
export NIRD_FLOW_DB_BATCH_SIZE=50000
export NIRD_DUCKDB_MEMORY_LIMIT=100GB
export NIRD_LOG_RSS_CHECKPOINTS=1
export NIRD_LCP_SORT_BY_DEST_COUNT=1
export NIRD_PATH_REALIZATION_STRATEGY=duckdb_chunked_compact

export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_stage1
export OMP_NUM_THREADS=1
export MKL_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1

# Log which resiflow actually got imported (must be under $CODE, not the shared checkout).
python -c "import resiflow; print('resiflow imported from:', resiflow.__file__)"

python $CODE/scripts/1_network_flow_model_revision.py 20 $SLURM_CPUS_PER_TASK
