"""OD fan-out stats for AFTER passenger OD (+ note full combined matrix size)."""
from pathlib import Path

import pandas as pd

od = pd.read_parquet(
    "/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/passenger_od_hpms_la.pq"
)
print("passenger_od rows", len(od), "origins", od["origin_node"].nunique(), "dests", od["destination_node"].nunique())
g = od.groupby(od["origin_node"].astype(str)).size().sort_values(ascending=False)
print("dests/origin: max", int(g.max()), "median", float(g.median()), "mean", float(g.mean()))
print("top 10 origins by dest count:\n", g.head(10))

# What the model actually assigns: freight+passenger combined (from log: 9.8M rows)
# Peek at soge freight OD path used by script if present
candidates = [
    Path("/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/isolated_base"),
]
print("done fanout")
