#!/bin/bash
#SBATCH --job-name=pytest_job
#SBATCH --partition=normal
# Run pytest on Hopper. Usage: sbatch --export=ALL,TESTS="tests/test_a.py tests/test_b.py -k name" this_script
# Do not export RESIFLOW_CONFIG_PATH / NIRD_CONFIG_PATH here: they override the toy test configs with real data.
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_pytest_job_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_pytest_job_%j.err
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
export PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data PROJ_LIB=$PROJ_DATA
CODE=${CODE:-/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_harvey}
cd $CODE
export PYTHONPATH=$CODE/src:/scratch/akothaw/multimodal_hazard_data/pytest_pkgs:$PYTHONPATH
git log --oneline -1 2>/dev/null
python -m pytest $TESTS -q -p no:cacheprovider --tb=short 2>&1 | grep -E "^(FAILED|ERROR|E  |/)|passed|failed" | head -60
