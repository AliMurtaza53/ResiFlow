import pandas as pd, glob, sys, json
R="/scratch/akothaw/multimodal_hazard_data/results"
out={}
for ev in sys.argv[1:]:
    var=f"smoke2_{ev}" if glob.glob(f"{R}/disruption_analysis/smoke2_{ev}/{ev}/links/*.gpq") else f"smoke_final_{ev}"
    f=glob.glob(f"{R}/disruption_analysis/{var}/{ev}/links/*.gpq")
    if not f: print(ev,"no links yet"); continue
    import pyarrow.parquet as pq
    names=pq.ParquetFile(f[0]).schema_arrow.names
    want=[c for c in names if c in ("damage_level_max","hazard_exposure_applicable","current_capacity","flood_depth_max","pga_max_g","landslide_max_mm","snow_depth_max","liquefaction_class_code","psa1p0_g") or c.endswith("_max") ]
    d=pq.read_table(f[0],columns=want).to_pandas()
    inten=[c for c in d.columns if c in ("flood_depth_max","pga_max_g","landslide_max_mm","snow_depth_max")] or [c for c in d.columns if c.endswith("_max") or c.endswith("_max_g") or c.endswith("_max_mm")]
    r={"var":var,"rows":len(d)}
    virt=d.get("hazard_exposure_applicable")
    if virt is not None:
        v=d[~virt.astype(bool)]
        r["virtual_links"]=len(v); r["virtual_with_damage_level>0"]=int((pd.to_numeric(v["damage_level_max"],errors="coerce").fillna(0)>0).sum())
    dl=pd.to_numeric(d["damage_level_max"],errors="coerce").fillna(0)
    r["links_damage_level>0"]=int((dl>0).sum()); r["damage_level_counts"]=dl.value_counts().sort_index().to_dict()
    for c in inten: r[c+"_max"]=float(pd.to_numeric(d[c],errors="coerce").max())
    r["zero_capacity"]=int((pd.to_numeric(d["current_capacity"],errors="coerce")<=0).sum())
    dm=glob.glob(f"{R}/damage_analysis/{var}/{ev}/*with_damage_values.csv")
    if dm:
        x=pd.read_csv(dm[0],low_memory=False); r["damage_rows"]=len(x); r["direct_damage_musd"]=float(x["direct_damage_mean_musd"].sum())
    out[ev]=r
print(json.dumps(out,indent=1,default=str))
