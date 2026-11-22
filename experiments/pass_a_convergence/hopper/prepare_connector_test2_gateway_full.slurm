#!/bin/bash
#SBATCH --job-name=ct2_gateway_full_prep
#SBATCH --partition=bigmem
#SBATCH --time=01:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=96G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_ct2_gateway_full_prep_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_ct2_gateway_full_prep_%j.err
set -eo pipefail
DATA=/scratch/akothaw/multimodal_hazard_data
OPS=$DATA/stage2_scripts/connector_test2_gateway_full
REF=$DATA/stage2_scripts/connector_test2_conus
H15=$DATA/stage2_scripts/connector_test2_cs
CODE=$DATA/code/ResiFlow_connector_endpoint
ENV=/scratch/akothaw/conda_envs/nird
export PATH="$ENV/bin:$PATH"
export PROJ_DATA=$ENV/lib/python3.10/site-packages/rasterio/proj_data PROJ_LIB=$ENV/lib/python3.10/site-packages/rasterio/proj_data
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
source "$CODE/experiments/common/profile_stage.sh"
profile_init ct2_gateway_full_prep
args=(python "$OPS/prepare_faf_gateway_pilot.py" "$OPS" "$DATA/stage2_scripts/connector_test1_inputs" "$REF"
    --regional "$OPS/regional.pq" --gateway-inventory "$OPS/gateway_inventory.csv")
# The fourth positional argument is the isolated output directory.
profile_stage prepare_harvey15 "${args[@]:0:5}" "$OPS/harvey15" "${args[@]:5}" \
    --county-crosswalk "$DATA/subset_harvey15/county_node_crosswalk_subset.csv" \
    --original-od "$DATA/subset_harvey15/faf5_od_matrix_subset.pq" \
    --control-od "$H15/harvey15_cs_assignment_parent_mean.pq" \
    --control-weights "$H15/weights_parent_mean.csv"
profile_stage prepare_conus "${args[@]:0:5}" "$OPS/conus" "${args[@]:5}" \
    --county-crosswalk "$CODE/parameters/crosswalks/county_node_crosswalk_conterminous.csv" \
    --original-od "$DATA/inputs_corrected/faf5_od_matrix_conterminous.pq" \
    --control-od "$REF/inputs/mean.pq" --control-weights "$REF/inputs/mean_weights.csv" \
    --road-nodes "$DATA/soge_clusters/networks/faf5/faf5_road_nodes.gpq"
profile_finish
