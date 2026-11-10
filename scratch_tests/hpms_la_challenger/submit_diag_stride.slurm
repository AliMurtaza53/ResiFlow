#!/bin/bash
#SBATCH --job-name=hpms_diag_stride
#SBATCH --partition=bigmem
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=400G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_hpms_diag_stride_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_hpms_diag_stride_%j.err

# Multi-origin smoke via stride (head-sample collapses to 1 origin).
# Stride 50 on ~9.8M combined OD ≈ 196k rows, many origins — enough to stress pool.

source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/config_hopper_hpms_la.json
export NIRD_CONFIG_PATH=$RESIFLOW_CONFIG_PATH
OUT=/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger
export NIRD_PASSENGER_OD_PATH="$OUT/passenger_od_hpms_la.pq"
export RESIFLOW_PASSENGER_OD_PATH="$OUT/passenger_od_hpms_la.pq"
export NIRD_MAX_FLOW_ITERATIONS=1
export NIRD_RESULTS_VARIANT=hpms_la_diag_stride
export NIRD_BASELINE_DB_PATH=/scratch/akothaw/multimodal_hazard_data/dbs/hpms_la_diag_stride.duckdb
export NIRD_DUCKDB_MEMORY_LIMIT=350GB
export NIRD_PATH_REALIZATION_STRATEGY=streaming_arrays
export PYTHONFAULTHANDLER=1

# Watchdog: if no Pool dispatch line within 20 min, dump procs and scancel self
(
  sleep 1200
  if ! grep -q "Pool dispatch" /home/akothaw/multimodal_hazard_project/logs_hpms_diag_stride_${SLURM_JOB_ID}.err 2>/dev/null; then
    echo "WATCHDOG: no Pool dispatch after 20m" >> /home/akothaw/multimodal_hazard_project/logs_hpms_diag_stride_${SLURM_JOB_ID}.err
    ps -u "$USER" -o pid,pcpu,stat,etime,cmd >> /home/akothaw/multimodal_hazard_project/logs_hpms_diag_stride_${SLURM_JOB_ID}.err
    scancel "$SLURM_JOB_ID"
  fi
) &

# argv: num_of_chunk num_of_cpu sample_stride
python -u /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/1_network_flow_model_revision.py 20 "$SLURM_CPUS_PER_TASK" 50
echo EXIT:$?
