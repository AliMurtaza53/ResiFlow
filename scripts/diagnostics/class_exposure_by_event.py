"""Share of each demand class's baseline link flow (VMT-weighted) that sits on damaged links, per event.
Preview of F vs P solo exposure before Stage 4. Read-only."""
import glob, sys, pandas as pd, numpy as np
R="/scratch/akothaw/multimodal_hazard_data/results"
def base(case):
    d=pd.read_parquet(f"{R}/finalA_{case}_baseline/edge_flows.gpq",columns=["e_id","acc_flow","length_mile","road_label","network_class"])
    d["vmt"]=d.acc_flow*d.length_mile; return d.set_index("e_id")
F,P=base("freight"),base("passenger")
print("baseline VMT/day  F=%.3gM  P=%.3gM  trips/trucks: F=%.3g P=%.3g"%(F.vmt.sum()/1e6,P.vmt.sum()/1e6,F.acc_flow.sum(),P.acc_flow.sum()))
rows=[]
for ev in sys.argv[1:]:
    f=glob.glob(f"{R}/disruption_analysis/smoke2_{ev}/{ev}/links/*.gpq")[0]
    L=pd.read_parquet(f,columns=["e_id","damage_level_max","current_capacity","hazard_exposure_applicable"]).drop_duplicates("e_id").set_index("e_id")
    dl=L.damage_level_max.astype(str)
    dmg=dl!="no"
    closed=dl.isin(["severe","extensive"])  # heavy damage
    r={"event":ev,"damaged_links":int(dmg.sum()),"heavy_links":int(closed.sum())}
    for nm,B in (("F",F),("P",P)):
        v=B.vmt.reindex(L.index).fillna(0); r[f"{nm}_vmt_on_damaged_%"]=round(100*v[dmg].sum()/B.vmt.sum(),3); r[f"{nm}_vmt_on_heavy_%"]=round(100*v[closed].sum()/B.vmt.sum(),3)
    rows.append(r)
print(pd.DataFrame(rows).to_string(index=False))
