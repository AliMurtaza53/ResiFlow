import numpy as np
import pandas as pd
import pyarrow.parquet as pq

D = "C:/Users/akothaw/Desktop/data"
lk = pq.read_table(f"{D}/soge_clusters/networks/faf5/faf5_road_links.bridge_tunnel_patched_hopper_2026-10-23.gpq",
                   columns=["e_id", "from_id", "to_id", "faf5_class", "assignment_tier", "lanes", "Road_Name", "STATE"]).to_pandas()
lk["e_id"] = lk.e_id.astype(str)
SAT = {1: [976918, 1197843, 1197845, 1063686], 2: [856886, 856888, 1063683, 1063698],
       3: [1194530, 1194525, 424455, 424464, 1422129, 419615, 419620, 419619, 1217556], 4: [1795099, 454955, 1151015, 1151010, 454947, 1151012]}
sat = pd.DataFrame([(it, e) for it, es in SAT.items() for e in es], columns=["iter", "e_id"]); sat["e_id"] = sat.e_id.astype(str)
sat = sat.merge(lk, on="e_id", how="left")
od = pq.read_table(f"{D}/soge_clusters/census_datasets/faf5_od_matrix.pq", columns=["origin_node", "destination_node", "Car21"]).to_pandas()
od_nodes = set(od.origin_node.astype("int64")) | set(od.destination_node.astype("int64"))
tot = od.groupby(od.origin_node.astype("int64")).Car21.sum().add(od.groupby(od.destination_node.astype("int64")).Car21.sum(), fill_value=0)
sat["from_is_od"] = sat.from_id.astype("int64").isin(od_nodes); sat["to_is_od"] = sat.to_id.astype("int64").isin(od_nodes)
print(f"saturated edges found in the links file: {sat.from_id.notna().sum()} of {len(sat)}")
print(f"  with an endpoint that is an OD (county) node as run: {int((sat.from_is_od | sat.to_is_od).sum())} of {len(sat)}")
print("  class of saturated edges:", sat.faf5_class.value_counts().to_dict(), "| tier:", sat.assignment_tier.value_counts().to_dict(), "| lanes:", sat.lanes.value_counts().to_dict())
print("  by iteration, endpoint is an OD node:", sat.groupby("iter").apply(lambda d: f"{int((d.from_is_od | d.to_is_od).sum())}/{len(d)}").to_dict())

# the OD nodes as run: degree and class of the links at each node
deg = pd.concat([lk.from_id.astype("int64"), lk.to_id.astype("int64")]).value_counts()
inc = pd.concat([pd.DataFrame({"node": lk.from_id.astype("int64"), "cls": lk.faf5_class, "tier": lk.assignment_tier}),
                 pd.DataFrame({"node": lk.to_id.astype("int64"), "cls": lk.faf5_class, "tier": lk.assignment_tier})])
inc = inc[inc.node.isin(od_nodes)]
nd = deg.reindex(sorted(od_nodes))
print(f"\nOD nodes as run: {len(od_nodes):,}; links at the node: median {nd.median():.0f}, share with 1 link {(nd == 1).mean():.1%}, 2 links {(nd == 2).mean():.1%}, 3 {(nd == 3).mean():.1%}, 4+ {(nd >= 4).mean():.1%}")
isramp = inc.groupby("node").cls.apply(lambda s: bool(s.isin([21, 22]).any()))
isfwy = inc.groupby("node").tier.apply(lambda s: bool((s == "freeway").any()))
print(f"  OD nodes touching a ramp link: {isramp.mean():.1%}; touching a freeway-tier link: {isfwy.mean():.1%}")
print("  link class at OD nodes (all incident links):", inc.cls.value_counts(normalize=True).head(6).round(3).to_dict())
top = tot.sort_values(ascending=False).head(1000)
print(f"  of the 1,000 busiest OD nodes (by trucks in+out): touching a ramp {isramp.reindex(top.index).mean():.1%}")
