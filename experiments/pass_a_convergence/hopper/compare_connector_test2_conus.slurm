#!/bin/bash
#SBATCH --job-name=ct2_conus_compare
#SBATCH --partition=normal
#SBATCH --time=00:30:00
#SBATCH --cpus-per-task=2
#SBATCH --mem=16G
#SBATCH --output=/home/akothaw/multimodal_hazard_project/logs_ct2_conus_compare_%j.out
#SBATCH --error=/home/akothaw/multimodal_hazard_project/logs_ct2_conus_compare_%j.err
set -eo pipefail
DATA=/scratch/akothaw/multimodal_hazard_data
OPS=$DATA/stage2_scripts/connector_test2_conus
CODE=$DATA/code/ResiFlow_connector_endpoint
PYTHON=/scratch/akothaw/conda_envs/nird/bin/python
export PATH="/scratch/akothaw/conda_envs/nird/bin:$PATH"
source "$CODE/experiments/common/profile_stage.sh"
profile_init ct2_conus_compare
profile_stage collect_link_flows "$PYTHON" - "$DATA" "$OPS" <<'PY'
from pathlib import Path
import sys

import pandas as pd

data, ops = map(Path, sys.argv[1:])
for arm in ("parent_only", "zero", "mean"):
    d = data / "results" / ("conus_connector_test2_" + arm)
    flows = pd.read_parquet(d / "edge_flows.gpq", columns=["e_id", "acc_flow"])
    flows.to_parquet(ops / f"comparison_{arm}.pq", index=False)
PY
profile_stage compare "$PYTHON" "$OPS/compare_faf_subcounty_flows.py" "$OPS" "$OPS"
profile_finish
