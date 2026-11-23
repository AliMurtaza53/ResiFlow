"""Bridge damage depends on WHICH link pieces set the whole-structure value. Current rule: max over
all pieces of the FAF link. Many bridges are a small fraction of their link, so the worst raster
cell may be on an approach, not the deck. Compare max / length-weighted mean / median. Read-only."""
import sys, glob, pandas as pd, numpy as np
R = "/scratch/akothaw/multimodal_hazard_data/results/damage_analysis"
pre = sys.argv[1]
for ev in sys.argv[2:]:
    f = glob.glob(f"{R}/{pre}{ev}/{ev}/*with_damage_values.csv")[0]
    d = pd.read_csv(f, usecols=["e_id","road_label","direct_damage_mean_musd","length","bridge_fraction"], low_memory=False)
    b = d[d.road_label=="bridge"].copy()
    b["w"] = b.length.clip(lower=1e-9); b["mw"] = b.direct_damage_mean_musd*b.w
    g = b.groupby("e_id").agg(mx=("direct_damage_mean_musd","max"), med=("direct_damage_mean_musd","median"),
                              mw=("mw","sum"), w=("w","sum"), bf=("bridge_fraction","first"), n=("w","size"))
    g["lwm"] = g.mw/g.w
    tot = g.mx.sum()
    small = g.bf < 0.25
    print(f"\n== {ev} bridges={len(g):,}  max-rule={g.mx.sum():,.0f}  length-weighted-mean={g.lwm.sum():,.0f}  median-piece={g.med.sum():,.0f}  (M USD)")
    print(f"   bridge_fraction quantiles: {g.bf.quantile([.1,.5,.9]).round(3).to_dict()}   share of max-rule damage on bridges that are <25% of their link: {g.mx[small].sum()/max(tot,1e-9):.0%}")
