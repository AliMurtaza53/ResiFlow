"""Recompute direct damage per event with the project's own aggregation
(bridge/tunnel once per link, roads summed) and break it down. Read-only.
Usage: recompute_event_damage.py <variant_prefix> <event> ..."""
import sys, glob, json
import pandas as pd
from resiflow.damage_aggregation import total_direct_damage_musd, collapse_to_edges
R = "/scratch/akothaw/multimodal_hazard_data/results/damage_analysis"
pre = sys.argv[1]
keep = ["e_id","road_label","direct_damage_mean_musd","direct_damage_mean_usd","STATE","road_classification","length","structure_length_m","averageWidth","landslide_mm","pga_g","psa1p0_g","flood_depth_surface","flood_depth_river","lanes"]
out = {}
for ev in sys.argv[2:]:
    f = glob.glob(f"{R}/{pre}{ev}/{ev}/*with_damage_values.csv")[0]
    hdr = pd.read_csv(f, nrows=0).columns
    d = pd.read_csv(f, usecols=[c for c in keep if c in hdr], low_memory=False)
    raw = float(d.direct_damage_mean_musd.sum())
    tot = float(total_direct_damage_musd(d))
    # per-link table: roads summed, bridge/tunnel max
    d["is_whole"] = d.road_label.isin(["bridge","tunnel"])
    w = d[d.is_whole].groupby("e_id").agg(m=("direct_damage_mean_musd","max"), label=("road_label","first"), st=("STATE","first"), rc=("road_classification","first"), L=("structure_length_m","first"), W=("averageWidth","first"))
    r = d[~d.is_whole].groupby("e_id").agg(m=("direct_damage_mean_musd","sum"), label=("road_label","first"), st=("STATE","first"), rc=("road_classification","first"))
    e = pd.concat([w, r])
    res = {"raw_row_sum": round(raw), "collapsed_total": round(tot, 1), "overcount_factor": round(raw/max(tot,1e-9),1),
           "by_asset": e.groupby("label").m.sum().round(1).to_dict(),
           "by_state_top5": e.groupby("st").m.sum().sort_values(ascending=False).head(5).round(1).to_dict(),
           "links_damaged": int((e.m>0).sum()),
           "top5_links": e.m.sort_values(ascending=False).head(5).round(1).to_dict()}
    # implausibility check: bridge damage over deck replacement scale
    b = w[w.label=="bridge"].copy()
    if len(b):
        b["deck_m2"] = b.L*b.W
        b["usd_per_m2"] = b.m*1e6/b.deck_m2
        res["bridge_damage_per_deck_m2_usd_quantiles"] = b.usd_per_m2.quantile([.5,.9,.99,1]).round(0).to_dict()
        res["bridge_damage_gt_1B"] = int((b.m>1000).sum())
    out[ev] = res
print(json.dumps(out, indent=1, default=str))
