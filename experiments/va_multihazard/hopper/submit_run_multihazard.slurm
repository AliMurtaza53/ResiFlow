#!/bin/bash
#SBATCH --job-name=va_multihazard_run
#SBATCH --partition=normal
# Runs the (Pass-B-free) multi-hazard orchestrator: Script 2 (disruption,
# full CONUS road network x VA-sized raster) -> Script 3 + 3_postprocess
# (direct damage) -> Script 4 (rerouting cost, reads Pass A's own odpfc.pq
# via a DuckDB-filtered scan) for each of the 4 real hazard events. NOT
# login-node-safe -- Script 2 loads/intersects the full 483K-edge CONUS
# network, and Script 4 scans a ~386GB baseline odpfc file; both got
# SIGKILL'd on hopper1's login node (2026-07-30) with no Python traceback,
# the classic OOM-on-shared-node signature already documented in
# docs/ORC_HOPPER_SETUP.md.
#
# --mem=128G to match NIRD_DUCKDB_MEMORY_LIMIT=100GB (orchestrator default,
# same as Pass A's own proven config) -- an earlier --mem=96G run OOM'd
# because DuckDB was told it could use more (100GB) than the job's actual
# memory ceiling (96GB), the same headroom mistake Pass A's tuning already
# had to learn from (see submit_cpu8_convergence.slurm).
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_run_multihazard_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_run_multihazard_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export RESIFLOW_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json
export NIRD_CONFIG_PATH=$HOME/multimodal_hazard_project/config_hopper.json

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/run_conus_va_multihazard.py \
  --hazards-manifest ~/multimodal_hazard_project/hazards.json \
  --results-variant convergence_cpu8_bounded18 \
  --num-chunks 20 --num-cpu $SLURM_CPUS_PER_TASK
