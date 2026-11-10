#!/bin/bash
#SBATCH --job-name=hpms_diag_many
#SBATCH --partition=bigmem
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=100G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_hpms_diag_many_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_hpms_diag_many_%j.err

source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
export PYTHONFAULTHANDLER=1
python -u /scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/diag_many_tasks_pool.py
echo EXIT:$?
