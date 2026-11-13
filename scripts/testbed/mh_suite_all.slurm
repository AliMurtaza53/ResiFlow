#!/bin/bash
# Sioux Falls all-hazards suite: 6 hazards x events 0,1,3,4,5,6 x time-dependent variants. Submit from a login node: sbatch scripts/testbed/mh_suite_all.slurm
# Uses its OWN checkout (not the Harvey one): git clone <repo> $CODE && git checkout feature/anaheim-assignment-diagnostics, then git pull --ff-only from a login shell.
#SBATCH --job-name=mh_suite
#SBATCH --partition=normal
#SBATCH --time=08:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=24G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_mh_suite_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_mh_suite_%j.err
module purge
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
export PROJ_DATA=/scratch/akothaw/conda_envs/nird/lib/python3.10/site-packages/rasterio/proj_data
export PROJ_LIB=$PROJ_DATA
export DISABLE_PANDERA_IMPORT_WARNING=True
CODE=${CODE:-/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_suite}
cd "$CODE" || exit 1
export PYTHONPATH=$CODE/src:/scratch/akothaw/multimodal_hazard_data/pytest_pkgs:$PYTHONPATH
git log --oneline -1
OUT=/scratch/akothaw/multimodal_hazard_data/mh_suite_$SLURM_JOB_ID
python scripts/diagnostics/inspect_multihazard_sioux_falls.py --out "$OUT" --variants all 2>&1 | grep -v -i "warn\|pandera\|^\s*$" | cut -c1-420
echo OUT=$OUT
