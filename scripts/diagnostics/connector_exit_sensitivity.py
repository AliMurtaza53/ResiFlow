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
                   columns=["from_id", "to_id", "length", "AB_FinalSpeed", "assignment_tier"]).to_pandas()
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

rng = np.random.default_rng(3)
sample = [int(x) for x in multi]
SPEEDS = [25.0, 30.0, 35.0, 1000.0]  # 1000 mph = connector time ~ 0
import warnings; warnings.filterwarnings("ignore")
cid_arr = np.array([int(cen.cid[k - nB]) for k in dest_v])
sample_fips = {int(cen.cid[k]) for k in sample}
ods = pads.dataset(f"{D}/soge_clusters/census_datasets/faf5_county_od.pq")
tb = ods.to_table(columns=["origin_county", "destination_county", "tons"], filter=pads.field("origin_county").isin([str(f).zfill(5) for f in sample_fips])).to_pandas()
tb["o"] = tb.origin_county.astype(int); tb["d"] = tb.destination_county.astype(int)
tons = tb.groupby(["o", "d"]).tons.sum()
print(f"county OD tons loaded for the {len(sample_fips)} origins: {tons.sum():,.0f} tons in {len(tons):,} county pairs")
rows = []
thru = 0; paths_total = 0
for k in sample:
    ov = nB + k
    first_by_speed = {}
    for s in SPEEDS:
        w = np.r_[w_road, conn_len / s]
        gr.es["w"] = w.tolist()
        paths = gr.get_shortest_paths(ov, to=dest_v, weights="w", output="epath")
        fe = np.array([p[0] if p else -1 for p in paths])
        first_by_speed[s] = fe
        if s == 25.0:
            for p in paths:
                if p:
                    paths_total += 1
                    if sum(1 for e in p if e >= n_road) >= 3:  # more than the origin and destination connector -> passes through a centroid
                        thru += 1
    f25, f30, f35, f0 = first_by_speed[25.0], first_by_speed[30.0], first_by_speed[35.0], first_by_speed[1000.0]
    valid = f25 >= 0
    wt = np.array([tons.get((int(cen.cid[k]), int(c)), 0.0) for c in cid_arr])
    own = np.flatnonzero(cen_idx == k)
    shares = pd.Series(f25[valid]).value_counts(normalize=True).sort_values(ascending=False)
    rows.append(dict(cid=int(cen.cid[k]), n_conn=len(own), conn_len_mi_min=float(conn_len[own].min()), conn_len_mi_max=float(conn_len[own].max()),
                     top_share=float(shares.iloc[0]), changed_25_to_35=float((f25[valid] != f35[valid]).mean()), changed_25_to_free=float((f25[valid] != f0[valid]).mean()),
                     w_changed_30=float(wt[valid & (f25 != f30)].sum() / max(wt[valid].sum(), 1e-9)), w_changed_35=float(wt[valid & (f25 != f35)].sum() / max(wt[valid].sum(), 1e-9)),
                     w_changed_free=float(wt[valid & (f25 != f0)].sum() / max(wt[valid].sum(), 1e-9)), tons=float(wt[valid].sum())))
r = pd.DataFrame(rows)
pd.set_option("display.width", 200)
print(f"\nsampled {len(r)} county centroids with 2+ connectors (all {len(dest_v):,} county destinations each)")
print(f"connectors per sampled centroid: {r.n_conn.value_counts().sort_index().to_dict()} | connector length (mi) min-of-origin median {r.conn_len_mi_min.median():.2f}, max-of-origin median {r.conn_len_mi_max.median():.2f}")
print(f"share of destinations using the busiest connector at 25 mph: median {r.top_share.median():.2f} (min {r.top_share.min():.2f}, max {r.top_share.max():.2f})")
print(f"destinations whose exit connector CHANGES when connector speed goes 25 -> 35 mph: median {r.changed_25_to_35.median():.1%}, mean {r.changed_25_to_35.mean():.1%}, max {r.changed_25_to_35.max():.1%}")
print(f"destinations whose exit connector CHANGES when connector time is ~0 (free access): median {r.changed_25_to_free.median():.1%}, mean {r.changed_25_to_free.mean():.1%}, max {r.changed_25_to_free.max():.1%}")
print(f"paths that pass THROUGH a centroid node (undirected graph, 25 mph): {thru:,} of {paths_total:,} ({thru / max(paths_total, 1):.2%})")
tw = r.tons.sum()
for lab, col in (("30 mph", "w_changed_30"), ("35 mph", "w_changed_35"), ("free access", "w_changed_free")):
    print(f"TONNAGE-WEIGHTED share of freight whose exit connector changes, 25 mph -> {lab}: {(r[col] * r.tons).sum() / tw:.2%}; centroids where >10% of their tonnage changes exit: {int((r[col] > 0.10).sum())} of {len(r)}")
print(r.sort_values("w_changed_35", ascending=False).head(8)[["cid", "n_conn", "conn_len_mi_min", "conn_len_mi_max", "top_share", "w_changed_35", "tons"]].round(3).to_string(index=False))
print(f"total {time.time() - t0:.0f}s")
