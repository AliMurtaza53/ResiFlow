"""Build a self-contained deck.gl HTML map of freight OD flows (county-to-county and state-to-state).

Inputs: corrected conterminous freight OD (node ids) + node->county crosswalk + TIGER county centroids.
Output: one HTML file (data embedded; basemap tiles and deck.gl load from the internet).
Flow unit: trucks/day (Car21); the build used a flat 20 t per truck.
"""
import json, sys
import numpy as np, pandas as pd, geopandas as gpd, pyarrow.parquet as pq

D = "C:/Users/akothaw/Desktop"
OD = f"{D}/data/soge_clusters/census_datasets_conterminous/faf5_od_matrix_conterminous.pq"
XW = f"{D}/ResiFlow/.worktrees/anaheim-diagnostics/parameters/crosswalks/county_node_crosswalk_conterminous.csv"
GPKG = f"{D}/gis_review/resiflow_od_review.gpkg"
OUT = sys.argv[1] if len(sys.argv) > 1 else "od_flow_map.html"
TOP_COUNTY_PAIRS = 15000

xw = pd.read_csv(XW).rename(columns={"node_id": "node"})
node2county = dict(zip(xw.node, xw.county_fips))
od = pq.read_table(OD).to_pandas()
od["o"] = od.origin_node.astype("int64").map(node2county)
od["d"] = od.destination_node.astype("int64").map(node2county)
unmapped = od.o.isna() | od.d.isna()
print(f"rows {len(od):,}; rows with an unmapped node: {unmapped.sum():,} (flow {od.Car21[unmapped].sum():,.0f})")
od = od[~unmapped].astype({"o": int, "d": int})
cc = od.groupby(["o", "d"], as_index=False).Car21.sum().rename(columns={"Car21": "trucks"})
total = cc.trucks.sum()
cc["same"] = cc.o == cc.d
print(f"county pairs {len(cc):,}; total {total:,.0f} trucks/day; within-county {cc.trucks[cc.same].sum() / total:.1%}")

cen = gpd.read_file(GPKG, layer="county_centroids_tiger")
print("centroid columns:", [c for c in cen.columns if c != "geometry"])
fcol = next(c for c in cen.columns if c.upper() in ("GEOID", "COUNTY_FIPS", "FIPS"))
ncol = next((c for c in cen.columns if c.upper() in ("NAMELSAD", "NAME")), fcol)
cen["fips"] = cen[fcol].astype(int)
ll = cen.to_crs(4326)
cen["lon"], cen["lat"] = ll.geometry.x, ll.geometry.y
pos = cen.set_index("fips")[["lon", "lat", ncol]].rename(columns={ncol: "name"})
pos = pos[~pos.index.duplicated()]

# state level (centroid = flow-weighted mean of its county centroids, by total tonnage in+out)
cc["so"], cc["sd"] = cc.o // 1000, cc.d // 1000
vol = pd.concat([cc.groupby("o").trucks.sum(), cc.groupby("d").trucks.sum()]).groupby(level=0).sum()
p = pos.join(vol.rename("w")).dropna(subset=["w"])
p["st"] = p.index // 1000
spos = p.groupby("st").apply(lambda g: pd.Series({"lon": np.average(g.lon, weights=g.w), "lat": np.average(g.lat, weights=g.w)}))
ss = cc.groupby(["so", "sd"], as_index=False).trucks.sum()

c2 = cc[~cc.same].sort_values("trucks", ascending=False).head(TOP_COUNTY_PAIRS)
print(f"county layer: top {len(c2):,} inter-county pairs = {c2.trucks.sum() / cc.trucks[~cc.same].sum():.1%} of inter-county flow")
c2 = c2[c2.o.isin(pos.index) & c2.d.isin(pos.index)]
cj = [[round(pos.lon[o], 4), round(pos.lat[o], 4), round(pos.lon[d], 4), round(pos.lat[d], 4), round(t, 1), int(o), int(d)]
      for o, d, t in zip(c2.o, c2.d, c2.trucks)]
sj = [[round(spos.lon[o], 3), round(spos.lat[o], 3), round(spos.lon[d], 3), round(spos.lat[d], 3), round(t, 1), int(o), int(d)]
      for o, d, t in zip(ss.so, ss.sd, ss.trucks) if o != d and o in spos.index and d in spos.index]
names = {int(k): v for k, v in pos.name.items()}
# per-county totals for node dots
tot = pd.concat([cc[~cc.same].groupby("o").trucks.sum(), cc[~cc.same].groupby("d").trucks.sum()]).groupby(level=0).sum()
dots = [[round(pos.lon[k], 4), round(pos.lat[k], 4), round(v, 1), int(k)] for k, v in tot.items() if k in pos.index]

html = open(__file__.replace("build_od_flow_map.py", "od_flow_map_template.html"), encoding="utf-8").read()
html = (html.replace("__COUNTY__", json.dumps(cj)).replace("__STATE__", json.dumps(sj))
        .replace("__DOTS__", json.dumps(dots)).replace("__NAMES__", json.dumps(names))
        .replace("__TOTAL__", f"{total:.0f}"))
open(OUT, "w", encoding="utf-8").write(html)
print("wrote", OUT, f"{len(html) / 1e6:.1f} MB")
