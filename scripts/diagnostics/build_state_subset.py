"""Subset the corrected freight OD to the top-15 Harvey-exchange states (all counties in them). The road network stays whole.

Only OD pairs with BOTH ends in the 15 states are kept; trips may route through any state. Outputs: subset OD, crosswalk, subset.json.
"""
import json, sys
from pathlib import Path
import pandas as pd, pyarrow.parquet as pq

D = "C:/Users/akothaw/Desktop/data/soge_clusters"
OD = f"{D}/census_datasets_conterminous/faf5_od_matrix_conterminous.pq"
XW = "C:/Users/akothaw/Desktop/ResiFlow/.worktrees/anaheim-diagnostics/parameters/crosswalks/county_node_crosswalk_conterminous.csv"
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else f"{D}/subset_harvey15")
STATES = {48: "TX", 22: "LA", 49: "UT", 40: "OK", 6: "CA", 12: "FL", 39: "OH", 17: "IL", 13: "GA", 5: "AR", 42: "PA", 36: "NY", 28: "MS", 26: "MI", 18: "IN"}

xw = pd.read_csv(XW)
n2s = dict(zip(xw.node_id, xw.state_fips))
od = pq.read_table(OD).to_pandas()
od["so"] = od.origin_node.astype("int64").map(n2s); od["sd"] = od.destination_node.astype("int64").map(n2s)
assert od.so.notna().all() and od.sd.notna().all()
keep = od.so.isin(STATES) & od.sd.isin(STATES)
sub = od[keep]
tot = od.Car21.sum()
n_c = int(xw.state_fips.isin(STATES).sum())
print(f"subset OD rows {len(sub):,} of {len(od):,}; flow {sub.Car21.sum():,.0f} of {tot:,.0f} trucks/day ({sub.Car21.sum() / tot:.1%}); counties {n_c}")
print("flow by origin state:", sub.groupby("so").Car21.sum().round(0).astype(int).rename(index=STATES).sort_values(ascending=False).to_dict())
OUT.mkdir(parents=True, exist_ok=True)
sub[["origin_node", "destination_node", "Car21"]].reset_index(drop=True).to_parquet(OUT / "faf5_od_matrix_subset.pq")
xw[xw.state_fips.isin(STATES)].to_csv(OUT / "county_node_crosswalk_subset.csv", index=False)
json.dump({"states": {str(k): v for k, v in STATES.items()}, "rows": len(sub), "counties": n_c,
           "flow_kept": float(sub.Car21.sum()), "flow_total": float(tot)}, open(OUT / "subset.json", "w"), indent=1)
print("wrote", OUT)
