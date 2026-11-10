#!/bin/bash
#SBATCH --job-name=hpms_lcp_bench
#SBATCH --partition=bigmem
#SBATCH --time=00:45:00
#SBATCH --cpus-per-task=8
#SBATCH --mem=100G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_hpms_lcp_bench_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_hpms_lcp_bench_%j.err

source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
export PYTHONFAULTHANDLER=1
cd /scratch/akothaw/multimodal_hazard_data/code/ResiFlow
/scratch/akothaw/conda_envs/nird/bin/python -u /scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/check_igraph_name_lookup.py
/scratch/akothaw/conda_envs/nird/bin/python -u /scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/bench_lcp_regression.py
echo EXIT:$?
