from pathlib import Path
import pandas as pd, geopandas as gpd, duckdb
R=Path("/scratch/akothaw/multimodal_hazard_data")
O=R/"stage2_scripts/gateway_gis_review_20261117"
cw=pd.read_csv(R/"stage2_scripts/connector_test2_conus/inputs/retained_ct_road_nodes.csv")
ids=cw.node_id.unique().tolist()
n=gpd.read_parquet(R/"soge_clusters/networks/faf5/faf5_road_nodes.gpq",filters=[("node_id","in",ids)])
n=n[["node_id","geometry"]].copy();n.node_id=n.node_id.astype(str)
d=duckdb.connect();d.execute("SET threads=2");d.execute("SET memory_limit='6GB'")
sel=",".join("'"+str(x)+"'" for x in ids)
for arm,tag in [("control","c"),("gateway","g")]:
 p=str(R/"results"/("conus_connector_test2g_"+arm)/"odpfc_parts/*.pq")
 d.execute("CREATE OR REPLACE VIEW p AS SELECT * FROM read_parquet('"+p+"')")
 out=d.execute("SELECT origin_node node,sum(flow) f FROM p WHERE origin_node IN ("+sel+") GROUP BY origin_node").df().set_index("node").f
 inn=d.execute("SELECT destination_node node,sum(flow) f FROM p WHERE destination_node IN ("+sel+") GROUP BY destination_node").df().set_index("node").f
 n["n_"+tag+"_out"]=n.node_id.map(out).fillna(0)
 n["n_"+tag+"_in"]=n.node_id.map(inn).fillna(0)
print(n.drop(columns="geometry").to_string(index=False),flush=True)
n.to_parquet(O/"ct_retained_road_nodes.gpq",index=False)
