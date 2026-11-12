import numpy as np
import pandas as pd
import geopandas as gpd
import pyarrow.parquet as pq

D = "C:/Users/akothaw/Desktop/data"
N = f"{D}/soge_clusters/networks/faf5"

# published reference: FAF5.7.1 2022 truck ton-miles and tons (domestic portion of the haul)
f5 = pd.read_csv(f"{D}/faf5_data/FAF5.7.1/FAF5.7.1.csv", usecols=["dms_mode", "trade_type", "tons_2022", "tmiles_2022"], dtype={"dms_mode": str})
tk = f5[(f5.dms_mode == "1") & (f5.tons_2022 > 0)]
print(f"FAF5.7.1 published: truck 2022 average haul = {tk.tmiles_2022.sum() * 1e6 / (tk.tons_2022.sum() * 1e3):.0f} miles (all trade types); "
      f"domestic trade only {tk[tk.trade_type == 1].tmiles_2022.sum() * 1e6 / (tk[tk.trade_type == 1].tons_2022.sum() * 1e3):.0f} miles")


def lonlat(path):
    g = gpd.read_parquet(path); g["node_id"] = g.node_id.astype("int64")
    g = g.set_index("node_id"); p = g.geometry.to_crs(4326)
    return pd.DataFrame({"lon": p.x, "lat": p.y}, index=g.index)


A = lonlat(f"{N}/faf5_road_nodes.gpq")                       # numbering the OD was built in (intended positions)
B = lonlat(f"{N}/faf5_road_nodes.hopper_2026-10-23.gpq")     # numbering the links and every run use (as-run positions)


def haversine_mi(lon1, lat1, lon2, lat2):
    r = np.pi / 180
    dlon = (lon2 - lon1) * r; dlat = (lat2 - lat1) * r
    h = np.sin(dlat / 2) ** 2 + np.cos(lat1 * r) * np.cos(lat2 * r) * np.sin(dlon / 2) ** 2
    return 3958.7613 * 2 * np.arcsin(np.sqrt(h))


def haul(od, pos, label):
    o = od.origin_node.astype("int64"); d = od.destination_node.astype("int64")
    a = pos.reindex(o.to_numpy()); b = pos.reindex(d.to_numpy())
    mi = haversine_mi(a.lon.to_numpy(), a.lat.to_numpy(), b.lon.to_numpy(), b.lat.to_numpy())
    w = od.Car21.to_numpy(); inter = (o.to_numpy() != d.to_numpy())
    mean_all = np.nansum(mi * w) / w.sum()
    mean_inter = np.nansum((mi * w)[inter]) / w[inter].sum()
    order = np.argsort(mi); cw = np.cumsum(w[order]) / w.sum()
    med = mi[order][np.searchsorted(cw, 0.5)]
    print(f"{label}: weighted mean straight-line haul {mean_all:,.0f} mi (excluding same-node pairs {mean_inter:,.0f}); weighted median {med:,.0f} mi; share of flow over 1,500 mi: {w[mi > 1500].sum() / w.sum():.1%}")


od = pq.read_table(f"{D}/soge_clusters/census_datasets/faf5_od_matrix.pq", columns=["origin_node", "destination_node", "Car21"]).to_pandas()
haul(od, A, "OD as built (intended positions, old numbering)   ")
haul(od, B, "OD as run (same ids, current numbering)            ")
odc = pq.read_table(f"{D}/soge_clusters/census_datasets_conterminous/faf5_od_matrix_conterminous.pq", columns=["origin_node", "destination_node", "Car21"]).to_pandas()
haul(odc, B, "corrected OD (re-snapped nodes, current numbering) ")
print("note: straight-line distance underestimates road distance by roughly 15-25%; FAF's figure is a road distance")
