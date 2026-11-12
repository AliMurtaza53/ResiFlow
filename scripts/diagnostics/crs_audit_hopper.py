import glob, json, os, sys
import numpy as np
import rasterio
from rasterio.warp import transform_bounds
from pyproj import CRS, Transformer

ROOT = "/scratch/akothaw/multimodal_hazard_data/soge_clusters"
out = {"rasters": [], "vectors": []}

# Houston and a few reference points (lon, lat) to test an unlabeled raster's georeference against candidate CRSs
HOUSTON = (-95.37, 29.76)

def crs_str(c):
    if c is None:
        return None
    try:
        e = c.to_epsg()
        return f"EPSG:{e}" if e else c.to_wkt()[:90]
    except Exception:
        return str(c)[:90]

for p in sorted(glob.glob(f"{ROOT}/inputs/multihazard_aligned/**/*.tif", recursive=True)):
    r = {"path": p.replace(ROOT + "/", ""), "size_mb": round(os.path.getsize(p) / 1e6, 1)}
    try:
        with rasterio.open(p) as ds:
            r.update(crs=crs_str(ds.crs), width=ds.width, height=ds.height, count=ds.count, dtype=ds.dtypes[0], nodata=ds.nodata,
                     res_x=ds.res[0], res_y=ds.res[1], bounds=[round(v, 4) for v in ds.bounds],
                     transform=list(ds.transform)[:6], tags={k: v for k, v in list(ds.tags().items())[:6]})
            # decimated read for value stats
            sc = max(1, max(ds.width, ds.height) // 800)
            a = ds.read(1, out_shape=(ds.height // sc, ds.width // sc), masked=True)
            v = a.compressed()
            r["valid_share"] = round(float(v.size / a.size), 4)
            if v.size:
                r["vmin"], r["vmax"], r["vmean"] = float(v.min()), float(v.max()), float(v.mean())
            if ds.crs is not None:
                r["bounds_lonlat"] = [round(x, 4) for x in transform_bounds(ds.crs, 4326, *ds.bounds)]
    except Exception as e:
        r["error"] = repr(e)
    out["rasters"].append(r)

import geopandas as gpd, pyarrow.parquet as pq
for p in sorted(glob.glob(f"{ROOT}/networks/faf5/*.gpq")):
    v = {"path": p.replace(ROOT + "/", ""), "size_mb": round(os.path.getsize(p) / 1e6, 1)}
    try:
        md = pq.read_metadata(p).metadata or {}
        geo = json.loads(md[b"geo"]) if b"geo" in md else {}
        col = geo.get("primary_column")
        cinfo = geo.get("columns", {}).get(col, {}) if col else {}
        c = CRS.from_user_input(cinfo["crs"]) if cinfo.get("crs") else None
        v.update(geom_col=col, crs=crs_str(c), crs_units=(c.axis_info[0].unit_name if c else None), bbox=cinfo.get("bbox"),
                 geometry_types=cinfo.get("geometry_types"), rows=pq.read_metadata(p).num_rows)
        if c is not None and cinfo.get("bbox"):
            v["bbox_lonlat"] = [round(x, 4) for x in transform_bounds(c, 4326, *cinfo["bbox"])]
    except Exception as e:
        v["error"] = repr(e)
    out["vectors"].append(v)

# Harvey: test the unlabeled raster against candidate CRSs
hv = next((r for r in out["rasters"] if "flood_harvey_houston" in r["path"]), None)
if hv and not hv.get("error"):
    b = hv["bounds"]
    tests = {}
    for name in ["EPSG:4326", "EPSG:5070", "EPSG:2163", "EPSG:3857", "EPSG:32615", "EPSG:26915", "EPSG:3081", "EPSG:2278", "EPSG:6588"]:
        try:
            t = Transformer.from_crs("EPSG:4326", name, always_xy=True)
            x, y = t.transform(*HOUSTON)
            tests[name] = {"houston_xy": [round(x, 1), round(y, 1)], "inside_bounds": bool(b[0] <= x <= b[2] and b[1] <= y <= b[3])}
        except Exception as e:
            tests[name] = {"error": repr(e)}
    hv["houston_in_candidate_crs"] = tests
json.dump(out, open("/tmp/crs_audit_akothaw.json", "w"), indent=1, default=str)
print(json.dumps(out, indent=1, default=str)[:12000])
