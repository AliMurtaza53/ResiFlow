#!/bin/bash
#SBATCH --job-name=path_join
#SBATCH --partition=normal
# Join stage 4 OD paths to the network. Usage: sbatch --export=ALL,VARIANT=<variant>,SCEN=<304|305>,DAYS="0 7"[,BASEVARIANT=<baseline variant if different, e.g. harvey_conus_corrected for Sandy>] this_script
#SBATCH --time=02:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=120G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_path_join_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_path_join_%j.err
source /home/akothaw/miniforge/bin/activate /scratch/akothaw/conda_envs/nird
CODE=${CODE:-/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_harvey}
DATA=/scratch/akothaw/multimodal_hazard_data
VARIANT=${VARIANT:-harvey_conus_corrected}
export PYTHONPATH=$CODE/src:$PYTHONPATH
source $CODE/experiments/common/profile_stage.sh
profile_init path_join_$VARIANT
profile_stage path_join python $CODE/scripts/diagnostics/join_rerouted_paths.py --results $DATA/results/rerouting_analysis/$VARIANT/${SCEN:-304}/1 --base-edges $DATA/results/${BASEVARIANT:-$VARIANT}/edge_flows.gpq --days ${DAYS:-0 7} --threads $SLURM_CPUS_PER_TASK
profile_finish
