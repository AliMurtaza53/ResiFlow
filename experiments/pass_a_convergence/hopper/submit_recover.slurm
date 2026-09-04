#!/bin/bash
#SBATCH --job-name=hazard_recover_conv
#SBATCH --partition=normal
# Recovery for convergence runs that didn't reach a clean stop (see
# scripts/recover_convergence_output.py). Do NOT run that script directly
# on a login node -- it was tried that way once and got silently OOM-killed
# (bare "Killed", no further detail) because login nodes are shared and
# memory-restricted, and the accumulated odpfc table across N iterations
# can be much bigger than the ~9.68M-row single-iteration table that
# already needed ~100GB + chunking earlier in this project. Mirroring the
# proven cpu8 resource envelope here rather than guessing a smaller one.
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=128G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_recover_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_recover_%j.err

module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird

export NIRD_DUCKDB_MEMORY_LIMIT=100GB
export NIRD_DUCKDB_TEMP_DIRECTORY=/scratch/akothaw/multimodal_hazard_data/duckdb_tmp_recover

python /scratch/akothaw/multimodal_hazard_data/code/ResiFlow/scripts/recover_convergence_output.py \
    --db /scratch/akothaw/multimodal_hazard_data/convergence_cpu8.duckdb \
    --out-dir /scratch/akothaw/multimodal_hazard_data/results/base_scenario/convergence_cpu8_recovered
