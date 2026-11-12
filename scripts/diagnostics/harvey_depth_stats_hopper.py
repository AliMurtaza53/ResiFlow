import rasterio, numpy as np
p="/scratch/akothaw/multimodal_hazard_data/soge_clusters/inputs/multihazard_aligned/flood_harvey_houston/event_1.tif"
with rasterio.open(p) as ds:
    a=ds.read(1,masked=True); print("shape",a.shape,"dtype",ds.dtypes[0],"nodata",ds.nodata)
    v=a.compressed().astype("float64"); print("valid px",v.size,"of",a.size)
    print("min/max/mean",v.min(),v.max(),v.mean())
    print("pct 50/90/99/99.9", np.percentile(v,[50,90,99,99.9]))
    for t in (0,0.1,0.5,1,3,5,10,18,30,100):
        print(f">{t}: {(v>t).sum()} ({(v>t).mean():.4%})")
    raw=a.data; print("unmasked min",raw.min(),"any NaN",np.isnan(raw).any())
