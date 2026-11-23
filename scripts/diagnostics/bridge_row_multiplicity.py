"""How many intersection rows does each bridge/tunnel link have, and how much of the
reported direct damage is that multiplicity? (read-only; works on any with_damage_values.csv)
Compares: reported sum of rows | once-per-link (max row) | once-per-link (mean row * 1)."""
import sys, glob, pandas as pd
R = "/scratch/akothaw/multimodal_hazard_data/results/damage_analysis"
pre = sys.argv[1]
use = ["e_id","road_label","direct_damage_mean_musd","length","structure_length_m","tunnel_length_m","STATE"]
for ev in sys.argv[2:]:
    f = glob.glob(f"{R}/{pre}{ev}/{ev}/*with_damage_values.csv")[0]
    hdr = pd.read_csv(f, nrows=0).columns
    d = pd.read_csv(f, usecols=[c for c in use if c in hdr], low_memory=False)
    d["m"] = d.direct_damage_mean_musd
    print(f"\n===== {ev} rows={len(d):,} reported={d.m.sum():,.0f} M USD")
    for lab, g in d.groupby("road_label"):
        per = g.groupby("e_id").m.agg(["size","sum","max","mean"])
        L = g.groupby("e_id").length.sum()
        print(f"{lab:7s} links={len(per):,} rows={int(per['size'].sum()):,} reported={per['sum'].sum():,.0f} "
              f"| once-per-link(max)={per['max'].sum():,.0f} | rows/link median={per['size'].median():.0f} p90={per['size'].quantile(.9):.0f} max={per['size'].max()}"
              f" | inflation(reported/max)={per['sum'].sum()/max(per['max'].sum(),1e-9):.1f}x")
    b = d[d.road_label=="bridge"]
    if len(b) and "structure_length_m" in b:
        per = b.groupby("e_id").agg(n=("m","size"), tot=("m","sum"), mx=("m","max"), seg=("length","sum"), st=("structure_length_m","first"))
        per["seg_over_struct"] = per.seg/per.st
        print("bridge: sum of row lengths / structure length  quantiles:", per.seg_over_struct.quantile([.1,.5,.9,.99]).round(2).to_dict(), "(units of 'length' vs metres: see ratio)")
