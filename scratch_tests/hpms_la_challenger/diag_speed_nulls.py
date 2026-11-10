"""Break down Speed_Limit / lanes / assignment_tier issues by network_source."""
from pathlib import Path

import geopandas as gpd
import pandas as pd

p = Path(
    "/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/"
    "isolated_base/networks/faf5/faf5_road_links.gpq"
)
g = gpd.read_parquet(p)
print("null Speed by source:")
print(
    g.groupby("network_source", dropna=False)
    .agg(n=("e_id", "size"), speed_null=("Speed_Limit", lambda s: int(s.isna().sum())))
)
print("\nlanes==0 by source:")
print(g[g["lanes"] == 0].groupby("network_source", dropna=False).size())
print("\nassignment_tier null by source:")
print(g[g["assignment_tier"].isna()].groupby("network_source", dropna=False).size())
print("\nHPMS Speed null frac", float(g.loc[g.network_source.eq("hpms_la"), "Speed_Limit"].isna().mean()))
print("xfer Speed null frac", float(g.loc[g.network_source.eq("hpms_faf_xfer"), "Speed_Limit"].isna().mean()))
print("xfer Speed value counts:")
print(g.loc[g.network_source.eq("hpms_faf_xfer"), "Speed_Limit"].value_counts(dropna=False).head())
# how many HPMS have speed filled?
hp = g[g.network_source.eq("hpms_la")]
print("HPMS speed describe non-null:")
print(hp["Speed_Limit"].dropna().describe())
print("HPMS lanes describe:")
print(hp["lanes"].describe())
