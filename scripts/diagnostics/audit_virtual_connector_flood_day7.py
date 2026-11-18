from pathlib import Path
import pandas as pd, igraph as ig
R=Path("/scratch/akothaw/multimodal_hazard_data")
O=R/"stage2_scripts/gateway_gis_review_20261117"
cw0=pd.read_csv(R/"stage2_scripts/connector_test1_inputs/connector_crosswalk.csv",dtype={"centroid_node":str,"road_node":str,"e_id":str})
summary=pd.read_csv(O/"virtual_connector_reachability_sensitivity.csv")
summary["day"]=0;summary["network_snapshot"]="initial day-0 physical graph"
more=[]
for scope in ["conus","harvey15"]:
 for arm in ["control","gateway"]:
  v=scope+"_connector_test2g_"+arm
  f=pd.read_parquet(R/"results/rerouting_analysis"/v/"304/1/edge_flows_freight_s1_day7.gpq",columns=["e_id","from_id","to_id","faf5_class","acc_speed","acc_capacity"])
  f.e_id=f.e_id.astype(str)
  roads=f[~f.faf5_class.eq(50).fillna(False)&f.acc_capacity.gt(0)&f.acc_speed.gt(0)]
  graph=ig.Graph.TupleList(roads[["from_id","to_id"]].astype(str).itertuples(index=False,name=None),directed=False)
  look=dict(zip(graph.vs["name"],graph.connected_components().membership))
  def component(n):return look.get(str(n),"isolated_"+str(n))
  cw=cw0.merge(f[["e_id","acc_speed","acc_capacity"]],on="e_id",how="left",validate="one_to_one")
  before={};after={}
  for n,z in cw.groupby("centroid_node"):
   before[n]=set(component(p) for p in z.loc[z.acc_speed.gt(0)&z.acc_capacity.gt(0),"road_node"])
   after[n]=set(component(p) for p in z.road_node)
  def access(n,table):return table.get(str(n),{component(n)})
  x=pd.read_parquet(R/"results/rerouting_analysis"/v/"304/1/trip_isolations_freight_s1_day7.pq")
  x["reachable_before"]=[bool(access(a,before)&access(b,before)) for a,b in zip(x.origin_node,x.destination_node)]
  x["reachable_if_virtual_reopened"]=[bool(access(a,after)&access(b,after)) for a,b in zip(x.origin_node,x.destination_node)]
  affected=x[~x.reachable_before&x.reachable_if_virtual_reopened]
  affected.to_parquet(O/(v+"_day7_virtual_closure_reachable_sensitivity.pq"),index=False)
  more.append({"scope":scope,"arm":arm,"day":7,"network_snapshot":"saved post-assignment day-7 physical graph","isolated_day0":x.flow.sum(),"isolated_but_initially_connected":x.loc[x.reachable_before,"flow"].sum(),"flow_with_path_if_virtual_connectors_reopened":affected.flow.sum(),"share_of_isolated":affected.flow.sum()/x.flow.sum(),"affected_od_rows":len(affected),"method":"saved physical speeds/capacities held; endpoint-only access; reopen virtual arcs only; no assignment rerun"})
summary=pd.concat([summary,pd.DataFrame(more)],ignore_index=True).rename(columns={"isolated_day0":"isolated_flow_at_day","isolated_but_initially_connected":"isolated_flow_reachable_in_reference_graph"})
summary.to_csv(O/"virtual_connector_reachability_sensitivity.csv",index=False)
print(summary.to_string(index=False),flush=True)
