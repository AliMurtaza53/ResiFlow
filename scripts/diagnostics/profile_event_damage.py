"""Profile one or more events' damage tables (registry rows s3_rollup_integrity,
s3_damage_per_mile, s2_damage_level_by_class, s2_exposure_intensity_hist).
Usage: profile_event_damage.py <variant_prefix> <event> [<event> ...]  (read-only)"""
import sys, glob, json
import pandas as pd, numpy as np
R = "/scratch/akothaw/multimodal_hazard_data/results/damage_analysis"
pre = sys.argv[1]
cols = ["e_id","length","landslide_mm","flood_depth_landslide","road_label","road_classification","STATE",
        "bridge_state","structure_length_m","tunnel_length_m","direct_damage_mean_musd","urban","lanes",
        "surface_unit_cost_max","river_unit_cost_max"]
for ev in sys.argv[2:]:
    f = glob.glob(f"{R}/{pre}{ev}/{ev}/*with_damage_values.csv")[0]
    hdr = pd.read_csv(f, nrows=0).columns
    d = pd.read_csv(f, usecols=[c for c in cols if c in hdr], low_memory=False)
    d["musd"] = d.direct_damage_mean_musd
    tot = d.musd.sum()
    print(f"\n===== {ev}  rows={len(d):,} unique_links={d.e_id.nunique():,} total={tot:,.0f} M USD")
    print("by asset (road_label):"); print(d.groupby("road_label").musd.agg(["count","sum"]).round(0).to_string())
    print("by road class:"); print(d.groupby("road_classification").musd.agg(["count","sum"]).sort_values("sum",ascending=False).head(8).round(0).to_string())
    print("by state top8:"); print(d.groupby("STATE").musd.sum().sort_values(ascending=False).head(8).round(0).to_string())
    inten = "landslide_mm" if "landslide_mm" in d else None
    if inten and d[inten].notna().any():
        x = d[inten].fillna(0)
        print("intensity quantiles (mm):", x.quantile([.5,.9,.99,1]).round(1).to_dict())
        bins = [-1,0,10,100,300,1000,3000,1e9]
        b = pd.cut(x, bins)
        print("damage by intensity bin:"); print(d.groupby(b, observed=True).musd.agg(["count","sum"]).round(0).to_string())
    # concentration
    s = d.groupby("e_id").musd.sum().sort_values(ascending=False)
    print("links carrying 50%/90% of damage:", int((s.cumsum()/tot<=.5).sum()+1), int((s.cumsum()/tot<=.9).sum()+1))
    print("top10 links:"); print(s.head(10).round(1).to_string())
    big = d.sort_values("musd",ascending=False).head(5)[["e_id","road_label","road_classification","STATE","length","landslide_mm","musd"]]
    print("top5 rows:"); print(big.to_string())
    if "length" in d: print("exposed length sum (km?):", round(d.length.sum(),1), " $M per unit length:", round(tot/max(d.length.sum(),1e-9),2))
