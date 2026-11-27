#!/bin/bash
#SBATCH --job-name=commodity_chain
#SBATCH --partition=bigmem
#SBATCH --time=03:00:00
#SBATCH --cpus-per-task=4
#SBATCH --mem=96G
#SBATCH --array=0-4
#SBATCH --output=/scratch/akothaw/multimodal_hazard_data/stage2_scripts/commodity_split_20261126/%x_%A_%a.out
# Per-commodity rerun of the frozen freight OD chain (rebuild -> subcounty split -> gateway), same inputs and
# arguments as payload_rebuild_20261122/split_gateway.slurm, with one sctgG5 group per array task.
# Sum over the five groups must equal freight_od_T29_gateway_conus.pq (see commodity_sum_gate.py).
set -eo pipefail
D=/scratch/akothaw/multimodal_hazard_data
W=$D/stage2_scripts/payload_rebuild_20261122
W2=$D/stage2_scripts/commodity_split_20261126
S=$W2/scripts/diagnostics
REF=$D/stage2_scripts/connector_test2_conus
GW=$D/stage2_scripts/connector_test2_gateway_full
CODE=$D/code/ResiFlow_connector_endpoint
C=$CODE/parameters/crosswalks
ENV=/scratch/akothaw/conda_envs/nird
export PATH=$ENV/bin:$PATH PROJ_DATA=$ENV/lib/python3.10/site-packages/rasterio/proj_data PROJ_LIB=$ENV/lib/python3.10/site-packages/rasterio/proj_data OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
export COMMODITY_SPLIT=1
GROUPS_LIST=(sctg0109 sctg1014 sctg1519 sctg2033 sctg3499)
K=${GROUPS_LIST[$SLURM_ARRAY_TASK_ID]}
O=$W2/$K
rm -rf $O; mkdir -p $O
echo "commodity $K"
python $S/rebuild_faf_od_payload.py --mode t29 --commodity $K --by-sctg $D/soge_clusters/census_datasets/faf5_od_matrix_by_sctg.pq \
  --t29 $W/T29_payload_conversion_factors.csv --remap-csv $C/conus_od_node_remap.csv \
  --crosswalk $C/county_node_crosswalk_conus_single_node.csv --out-dir $O/t29
python $S/prepare_faf_conus_subcounty_od.py $O/t29/faf5_od_matrix_t29_conterminous.pq $C/county_node_crosswalk_conterminous.csv \
  $D/stage2_scripts/connector_test1_inputs/connector_crosswalk.csv $D/soge_clusters/networks/faf5/faf5_road_nodes.gpq $REF $O/split
python $S/prepare_faf_gateway_pilot.py $GW $D/stage2_scripts/connector_test1_inputs $REF $O/conus \
  --regional $GW/regional.pq --gateway-inventory $GW/gateway_inventory.csv --county-crosswalk $C/county_node_crosswalk_conterminous.csv \
  --original-od $O/t29/faf5_od_matrix_t29_conterminous.pq --control-od $O/split/mean.pq --control-weights $O/split/mean_weights.csv \
  --road-nodes $D/soge_clusters/networks/faf5/faf5_road_nodes.gpq --payload-table $W/T29_payload_conversion_factors.csv --commodity $K
echo "done $K"
