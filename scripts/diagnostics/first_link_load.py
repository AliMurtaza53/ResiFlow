"""Prototype: restore the FAF5 Class 50 centroid connectors on the current CONUS graph and measure how connector speed changes which
connector (exit) trips from multi-connector county centroids use. Shortest paths only (the model's all-or-nothing step); no assignment, no capacity."""
import time
import numpy as np
import pandas as pd
import geopandas as gpd
import pyarrow.parquet as pq
import igraph as ig
from scipy.spatial import cKDTree
import shapely
import pyarrow.dataset as pads

D = "C:/Users/akothaw/Desktop/data"
G = f"{D}/faf5_data/network_data/FAF5Network.gdb"
t0 = time.time()

lk = pq.read_table(f"{D}/soge_clusters/networks/faf5/faf5_road_links.bridge_tunnel_patched_hopper_2026-10-23.gpq",
                   columns=["from_id", "to_id", "length", "AB_FinalSpeed", "assignment_tier", "faf5_class", "lanes"]).to_pandas()
med = float(lk.length.median())
len_mi = lk.length.astype(float) if med < 20 else lk.length.astype(float) / 1609.344
spd = pd.to_numeric(lk.AB_FinalSpeed, errors="coerce")
spd = spd.fillna(spd.groupby(lk.assignment_tier).transform("median")).fillna(35.0).clip(lower=5.0)
w_road = (len_mi / spd).to_numpy()
print(f"road links {len(lk):,}; 'length' median {med:.3g} -> treated as {'miles' if med < 20 else 'metres'}; speed median {spd.median():.0f} mph")

nodesB = gpd.read_parquet(f"{D}/soge_clusters/networks/faf5/faf5_road_nodes.hopper_2026-10-23.gpq")
nodesB["node_id"] = nodesB.node_id.astype("int64"); nodesB = nodesB.set_index("node_id")
a = lk.from_id.astype("int64").to_numpy(); b = lk.to_id.astype("int64").to_numpy()
ids = np.unique(np.concatenate([a, b])); pos = pd.Series(np.arange(len(ids)), index=ids)
ea = pos.reindex(a).to_numpy(); eb = pos.reindex(b).to_numpy()
nB = len(ids)
bx = nodesB.geometry.reindex(ids); btree = cKDTree(np.c_[bx.x, bx.y])

allnodes = gpd.read_file(G, layer="FAF5_Nodes", engine="pyogrio", columns=["Centroid", "CentroidID"])
cen = allnodes[allnodes.Centroid == 1].drop_duplicates("CentroidID").copy().to_crs(2163)
cen["cid"] = cen.CentroidID.astype("int64"); cen = cen.reset_index(drop=True)
ctree = cKDTree(np.c_[cen.geometry.x, cen.geometry.y])
con = gpd.read_file(G, layer="FAF5_Links", engine="pyogrio", where="Class = 50", columns=["ID", "Class", "LENGTH"]).to_crs(2163)
g = con.geometry.values; n = shapely.get_num_geometries(g)
first = shapely.get_point(shapely.get_geometry(g, 0), 0)
last = np.array([shapely.get_point(shapely.get_geometry(g[i], int(n[i]) - 1), -1) for i in range(len(g))], dtype=object)
P0 = np.c_[shapely.get_x(first), shapely.get_y(first)]; P1 = np.c_[shapely.get_x(last), shapely.get_y(last)]
d0, i0 = ctree.query(P0); d1, i1 = ctree.query(P1)
cen_end_is_first = d0 <= d1
cen_idx = np.where(cen_end_is_first, i0, i1)
road_pt = np.where(cen_end_is_first[:, None], P1, P0)
dr, ir = btree.query(road_pt)
print(f"connectors {len(con):,}: centroid end matched (max {np.minimum(d0, d1).max():.1f} m); road end -> nearest road node: median {np.median(dr):.0f} m, p99 {np.quantile(dr, .99):.0f} m, max {dr.max():.0f} m")
keep = dr < 300
con = con[keep].reset_index(drop=True); cen_idx = cen_idx[keep]; ir = ir[keep]
cv = nB + cen_idx                      # centroid vertex index
conn_len = con.LENGTH.astype(float).to_numpy()

nV = nB + len(cen)
edges = np.r_[np.c_[ea, eb], np.c_[cv, ir]]
gr = ig.Graph(n=nV, edges=edges.tolist(), directed=False)
n_road = len(lk)
cid_by_v = {int(nB + k): int(c) for k, c in enumerate(cen.cid)}
conn_per_centroid = pd.Series(cen_idx).value_counts()
multi = [k for k, cnt in conn_per_centroid.items() if cnt >= 2 and cen.cid[k] <= 56999]
dest_v = [nB + k for k in range(len(cen)) if cen.cid[k] <= 56999]
print(f"graph: {nV:,} vertices, {gr.ecount():,} edges; centroids with 2+ connectors (county FIPS): {len(multi)}; destinations {len(dest_v):,}; build {time.time() - t0:.0f}s")


import warnings; warnings.filterwarnings("ignore")
cls = pd.to_numeric(lk.faf5_class, errors="coerce").to_numpy(); tier = lk.assignment_tier.astype(str).to_numpy(); lanes = pd.to_numeric(lk.lanes, errors="coerce").fillna(1).to_numpy()
PLPH = {"freeway": 2350, "arterial": 900, "collector": 700, "local_access": 550}
cap_day = np.array([PLPH.get(t, 700) for t in tier]) * np.maximum(lanes, 1) * 24.0
CLS = {11: "interstate", 12: "other freeway/expressway", 14: "arterial/major collector", 15: "local", 16: "frontage/service", 17: "traffic circle", 19: "facility access", 21: "system ramp", 22: "ramp", 23: "collector/distributor", 13: "non-controlled Interstate (AK)", 41: "ferry"}
w = np.r_[w_road, conn_len / 25.0]; gr.es["w"] = w.tolist()
cid_arr = np.array([int(cen.cid[k - nB]) for k in dest_v])
ods = pads.dataset(f"{D}/soge_clusters/census_datasets/faf5_county_od.pq")
cty = [k for k in range(len(cen)) if cen.cid[k] <= 56999]
tb = ods.to_table(columns=["origin_county", "destination_county", "tons"]).to_pandas()
tb["o"] = tb.origin_county.astype(int); tb["d"] = tb.destination_county.astype(int)
out_tons = tb.groupby("o").tons.sum().sort_values(ascending=False)
top = [int(x) for x in out_tons.index[:150]]
rng = np.random.default_rng(7); rest = [int(x) for x in out_tons.index[150:]]; rnd = [int(x) for x in rng.choice(rest, size=150, replace=False)]
cid_to_k = {int(c): k for k, c in enumerate(cen.cid)}
pair = tb.groupby(["o", "d"]).tons.sum()
rows = []
t1 = time.time()
for grp, lst in (("top-150 by tonnage", top), ("random-150", rnd)):
    for f in lst:
        k = cid_to_k.get(f)
        if k is None: continue
        ov = nB + k
        paths = gr.get_shortest_paths(ov, to=dest_v, weights="w", output="epath")
        tonnage = {}
        for p, c in zip(paths, cid_arr):
            if len(p) >= 2 and p[0] >= n_road and p[1] < n_road:
                tonnage[p[1]] = tonnage.get(p[1], 0.0) + pair.get((f, int(c)), 0.0)
        if not tonnage: continue
        s_ = pd.Series(tonnage).sort_values(ascending=False); tot_t = s_.sum()
        e1 = int(s_.index[0]); trucks_day = s_.iloc[0] / 20.0 / 365.0
        rows.append(dict(group=grp, fips=f, tons=tot_t, n_first_links=int((s_ > 0).sum()), top1_share=s_.iloc[0] / tot_t, links_for_90=int((s_.cumsum() / tot_t < 0.9).sum() + 1),
                         top_class=CLS.get(int(cls[e1]) if not np.isnan(cls[e1]) else -1, str(cls[e1])), top_tier=tier[e1], top_trucks_day=trucks_day, top_cap_day=cap_day[e1], util=trucks_day / cap_day[e1]))
r = pd.DataFrame(rows)
pd.set_option("display.width", 200)
print(f"\norigins analysed: {len(r)} ({time.time() - t1:.0f}s); freight trucks/day estimated as tons / 20 t / 365 (flat payload)")
for g, d in r.groupby("group"):
    print(f"\n[{g}] origins {len(d)}: busiest first road link carries median {d.top1_share.median():.0%} of the county's tonnage (p10 {d.top1_share.quantile(.1):.0%}, p90 {d.top1_share.quantile(.9):.0%}); links needed for 90%: median {d.links_for_90.median():.0f}")
    print(f"   class of the busiest first link: {d.top_class.value_counts(normalize=True).round(2).to_dict()}")
    print(f"   freight-only utilisation of that link: median {d.util.median():.0%}, p90 {d.util.quantile(.9):.0%}, max {d.util.max():.0%}; origins above 100%: {int((d.util > 1).sum())}; above 50%: {int((d.util > .5).sum())}")
print("\nlargest origins:"); print(r.sort_values("tons", ascending=False).head(8)[["fips", "tons", "top1_share", "links_for_90", "top_class", "top_trucks_day", "top_cap_day", "util"]].round(2).to_string(index=False))
