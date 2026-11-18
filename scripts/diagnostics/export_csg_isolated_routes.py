from pathlib import Path
import duckdb, pandas as pd
R=Path("/scratch/akothaw/multimodal_hazard_data")
O=R/"stage2_scripts/gateway_gis_review_20261117"
d=duckdb.connect();d.execute("SET threads=2");d.execute("SET memory_limit='20GB'")
keys=pd.read_csv(R/"stage2_scripts/connector_test1_inputs/connector_crosswalk.csv")
gs=keys.loc[keys.centroid_id.between(100005,100411),"centroid_node"].astype(str).unique()
g=",".join("'"+x+"'" for x in gs)
for scope,pre in [("conus","n"),("harvey15","h")]:
 for arm,tag in [("control","c"),("gateway","g")]:
  variant=scope+"_connector_test2g_"+arm
  p=str(R/"results"/variant/"odpfc_parts/*.pq")
  iso=str(R/"results/rerouting_analysis"/variant/"304/1/trip_isolations_freight_s1_day0.pq")
  d.execute("CREATE OR REPLACE VIEW iso AS SELECT origin_node,destination_node,sum(flow) isolated_flow FROM read_parquet('"+iso+"') GROUP BY ALL")
  pairs=d.execute("""WITH candidates AS (
   (SELECT * FROM iso ORDER BY isolated_flow DESC,origin_node,destination_node LIMIT 250)
   UNION SELECT origin_node,destination_node,isolated_flow FROM (SELECT *,row_number() OVER(PARTITION BY origin_node ORDER BY isolated_flow DESC,destination_node) rn FROM iso WHERE origin_node IN ("""+g+""")) WHERE rn=1
   UNION SELECT origin_node,destination_node,isolated_flow FROM (SELECT *,row_number() OVER(PARTITION BY destination_node ORDER BY isolated_flow DESC,origin_node) rn FROM iso WHERE destination_node IN ("""+g+""")) WHERE rn=1)
   SELECT DISTINCT * FROM candidates""").df()
  d.register("pairs",pairs)
  rows=d.execute("SELECT p.*,pairs.isolated_flow FROM read_parquet('"+p+"') p JOIN pairs USING(origin_node,destination_node)").df()
  assert len(rows)>=len(pairs),(variant,len(rows),len(pairs))
  rows.to_parquet(O/(pre+"_"+tag+"_d0_isolated_baseline_paths.pq"),index=False)
  print(variant,len(rows),flush=True)
