from pathlib import Path
import pandas as pd, igraph as ig, json
R=Path("/scratch/akothaw/multimodal_hazard_data")
O=R/"stage2_scripts/gateway_gis_review_20261117"
cols=["e_id","from_id","to_id","faf5_class","current_capacity","max_speed","max_speed_truck","flood_depth_max","damage_level_max"]
f=pd.read_parquet(R/"results/disruption_analysis/conus_connector_test2g_gateway/304/links/road_links_1.gpq",columns=cols)
f.e_id=f.e_id.astype(str)
roads=f[~f.faf5_class.eq(50).fillna(False)&f.current_capacity.gt(.5)&f.max_speed.gt(0)]
graph=ig.Graph.TupleList(roads[["from_id","to_id"]].astype(str).itertuples(index=False,name=None),directed=False)
comp=graph.connected_components().membership
lookup=dict(zip(graph.vs["name"],comp))
def component(node):return lookup.get(str(node),"isolated_road_"+str(node))
cw=pd.read_csv(R/"stage2_scripts/connector_test1_inputs/connector_crosswalk.csv",dtype={"centroid_node":str,"road_node":str,"e_id":str})
cw=cw.merge(f[["e_id","max_speed"]],on="e_id",validate="one_to_one")
before={};after={}
for n,z in cw.groupby("centroid_node"):
 before[n]=set(component(p) for p in z.loc[z.max_speed.gt(0),"road_node"])
 after[n]=set(component(p) for p in z.road_node)
def access(n,table):return table.get(str(n),{component(n)})
summary=[]
for scope in ["conus","harvey15"]:
 for arm in ["control","gateway"]:
  v=scope+"_connector_test2g_"+arm
  x=pd.read_parquet(R/"results/rerouting_analysis"/v/"304/1/trip_isolations_freight_s1_day0.pq")
  x["reachable_before"]=[bool(access(a,before)&access(b,before)) for a,b in zip(x.origin_node,x.destination_node)]
  x["reachable_if_virtual_reopened"]=[bool(access(a,after)&access(b,after)) for a,b in zip(x.origin_node,x.destination_node)]
  x["virtual_closure_changes_reachability"]=~x.reachable_before & x.reachable_if_virtual_reopened
  affected=x[x.virtual_closure_changes_reachability]
  affected.to_parquet(O/(v+"_virtual_closure_reachable_sensitivity.pq"),index=False)
  summary.append({"scope":scope,"arm":arm,"isolated_day0":x.flow.sum(),"isolated_but_initially_connected":x.loc[x.reachable_before,"flow"].sum(),"flow_with_path_if_virtual_connectors_reopened":affected.flow.sum(),"share_of_isolated":affected.flow.sum()/x.flow.sum(),"affected_od_rows":len(affected),"method":"initial day-0 physical graph; endpoint-only access; all physical closures held; no capacity assignment rerun"})
pd.DataFrame(summary).to_csv(O/"virtual_connector_reachability_sensitivity.csv",index=False)
closed=f[f.faf5_class.eq(50)&f.max_speed.le(0)]
ends=set(cw[cw.e_id.isin(closed.e_id)].road_node)
adj=f[~f.faf5_class.eq(50).fillna(False)&(f.from_id.astype(str).isin(ends)|f.to_id.astype(str).isin(ends))]
adj.to_csv(O/"physical_roads_at_closed_connector_ends.csv",index=False)
print(pd.DataFrame(summary).to_string(index=False),flush=True)
