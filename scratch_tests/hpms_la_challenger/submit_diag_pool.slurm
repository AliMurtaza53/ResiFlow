#!/bin/bash
#SBATCH --job-name=hpms_diag_pool
#SBATCH --partition=bigmem
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=100G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_hpms_diag_pool_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_hpms_diag_pool_%j.err

source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
export DIAG_NCPU=4
# Fail fast if workers die: Python 3.8+ 
export PYTHONFAULTHANDLER=1
python -u /scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/diag_pool_repro.py
echo EXIT:$?
