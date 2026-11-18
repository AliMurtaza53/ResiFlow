"""Build the local reading guide, decision report, and QGIS project."""
from pathlib import Path
import json, html, sqlite3, hashlib, sys
import xml.etree.ElementTree as ET
import pandas as pd
import numpy as np
import geopandas as gpd
import pyogrio
P=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parent
ref=Path("C:/Users/akothaw/Desktop/ResiFlow/faf5_2022_assignment_review.gpkg")
layers=pd.read_csv(P/"gis_layers.csv").drop_duplicates("layer",keep="last")
b=pd.read_csv(P/"baseline_summary.csv")
r=pd.read_csv(P/"recovery_summary.csv")
m=pd.read_csv(P/"official_road_agreement.csv")
g=pd.read_csv(P/"decision_checks.csv")
pc=pd.read_csv(P/"all_path_change_statistics.csv")
manifest=json.loads((P/"manifest.json").read_text())
# Consolidate whole-structure costs exactly as the production damage postprocessor:
# roads sum their cell pieces; bridges and tunnels take the maximum once per link.
d=pd.read_parquet(P/"conus_connector_test2g_gateway_damage_rows.pq")
d.e_id=d.e_id.astype(str)
asset=d.road_label.astype(str).str.lower().isin(["bridge","tunnel"])
cost=pd.concat([d.loc[~asset].groupby("e_id").direct_damage_mean_usd.sum(),d.loc[asset].groupby("e_id").direct_damage_mean_usd.max()]).groupby(level=0).sum()
old=gpd.read_file(P/"CSG_review.gpkg",layer="harvey_flood_damage_links")
old.e_id=old.e_id.astype(str);old["damage_usd"]=old.e_id.map(cost)
old.to_file(P/"CSG_review.gpkg",layer="harvey_flood_damage_links",driver="GPKG",index=False)
dl=old.merge(d[["e_id","road_label"]].drop_duplicates(),on="e_id",validate="one_to_one")
da=dl.groupby("road_label",dropna=False).agg(damage_usd=("damage_usd","sum"),damaged_links=("e_id","size"),damage_bearing_geodesic_m=("damaged_length_geodesic_m","sum")).reset_index()
da.to_csv(P/"damage_by_asset.csv",index=False)
expected=r.direct_damage_total_usd.iloc[0]
assert np.isclose(cost.sum(),expected,rtol=1e-9), (cost.sum(),expected)
assert np.allclose(r.direct_damage_total_usd,expected,rtol=1e-9)
wet=pd.read_parquet(P/"flood_intersections_all.pq");wet.e_id=wet.e_id.astype(str)
roads0=gpd.read_file(P/"CSG_review.gpkg",layer="roads_baseline_comparison")
roads0.e_id=roads0.e_id.astype(str)
classes=pd.read_parquet(P/"physical_road_class_reference.pq");classes.e_id=classes.e_id.astype(str)
roads0=roads0.drop(columns=["hpms_fclass","road_label"],errors="ignore").merge(classes,on="e_id",how="left",validate="one_to_one")
with sqlite3.connect(ref.resolve().as_uri()+"?mode=ro",uri=True) as source:
    names0=pd.read_sql_query("SELECT CAST(link_id AS TEXT) e_id,Road_Name FROM resiflow_roads_official_faf5_flows",source)
roads0=roads0.drop(columns=["Road_Name"],errors="ignore").merge(names0,on="e_id",how="left",validate="one_to_one")
for pre in ["n","h"]:
    roads0[pre+"_abs_error_c"]=(roads0[pre+"_c_flow"]-roads0.official).abs()
    roads0[pre+"_abs_error_g"]=(roads0[pre+"_g_flow"]-roads0.official).abs()
    roads0[pre+"_delta_abs_error"]=roads0[pre+"_abs_error_g"]-roads0[pre+"_abs_error_c"]
roads0.to_file(P/"CSG_review.gpkg",layer="roads_baseline_comparison",driver="GPKG",index=False)
error_parts=[]
accessids=set(pd.read_csv(P/"conus_gateway_access_roads.csv").e_id.astype(str))
for name,fips in [("Los_Angeles",6037),("Harris",48201)]:
    z=roads0[pd.to_numeric(roads0.CTFIPS,errors="coerce").eq(fips)&roads0.official.notna()].copy()
    z["gateway_access_road"]=z.e_id.isin(accessids)
    for label,q in [("gateway_access",z[z.gateway_access_road]),("other_roads",z[~z.gateway_access_road])]:
        error_parts.append({"county":name,"roads":label,"links":len(q),"control_abs_error":q.n_abs_error_c.sum(),"gateway_abs_error":q.n_abs_error_g.sum(),"delta_abs_error":q.n_delta_abs_error.sum()})
    z.drop(columns="geometry").sort_values("n_delta_abs_error",ascending=False).head(50).to_csv(P/(name+"_largest_error_increases.csv"),index=False)
    z.drop(columns="geometry").sort_values("n_delta_abs_error").head(50).to_csv(P/(name+"_largest_error_decreases.csv"),index=False)
    z.groupby("hpms_fclass",dropna=False).agg(links=("e_id","size"),control_abs_error=("n_abs_error_c","sum"),gateway_abs_error=("n_abs_error_g","sum"),delta_abs_error=("n_delta_abs_error","sum")).to_csv(P/(name+"_error_by_functional_class.csv"))
error_parts=pd.DataFrame(error_parts);error_parts.to_csv(P/"county_error_access_vs_other_roads.csv",index=False)
wet=wet.merge(roads0[["e_id","faf5_class","hpms_fclass","road_label"]],on="e_id",how="left",validate="many_to_one")
wet["asset"]=wet.road_label.fillna("unknown")
wet["class_group"]=np.select([wet.hpms_fclass.isin([1,2,3]),wet.hpms_fclass.isin([4,5,6,7])],["F1-F3","F4-F7"],default="unknown_HPMS_class")
wet["wet"]=wet.flood_depth_surface.gt(0)
floodstats=wet.groupby(["class_group","asset"],dropna=False).agg(pieces=("e_id","size"),wet_pieces=("wet","sum"),links=("e_id","nunique"),wet_geodesic_m=("length_geodesic_m",lambda s: s[wet.loc[s.index,"wet"]].sum())).reset_index()
wl=wet[wet.wet].groupby(["class_group","asset"]).e_id.nunique()
floodstats["wet_links"]=[wl.get((x.class_group,x.asset),0) for x in floodstats.itertuples()]
floodstats["wet_piece_share"]=floodstats.wet_pieces/floodstats.pieces
floodstats.to_csv(P/"flooded_links_by_class_and_asset.csv",index=False)
depth=wet.groupby("e_id").flood_depth_surface.max()
depthstats=depth.describe(percentiles=[.01,.5,.95,.99]).rename("max_link_depth_m").reset_index()
depthstats.to_csv(P/"link_depth_summary.csv",index=False)
depthbins=pd.cut(depth,[-np.inf,0,.1,.3,.5,1,2,9.144,np.inf])
depthbins.value_counts(sort=False).rename_axis("max_link_depth_m").rename("links").to_csv(P/"depth_distribution.csv")
allwet=roads0[roads0.e_id.isin(depth[depth.gt(0)].index)][["e_id","faf5_class","hpms_fclass","road_label","road_bridge","geometry"]].copy()
allwet["max_depth_m"]=allwet.e_id.map(depth)
allwet["damage_usd"]=allwet.e_id.map(cost).fillna(0)
allwet.to_file(P/"CSG_review.gpkg",layer="harvey_all_wet_links",driver="GPKG",index=False)
layers=pd.concat([layers,pd.DataFrame([{"layer":"harvey_all_wet_links","features":len(allwet)}])],ignore_index=True).drop_duplicates("layer",keep="last")
layers.to_csv(P/"gis_layers.csv",index=False)
lc=json.loads((P/"length_check_1.json").read_text())
ok=wet.length.ge(1)&wet.length_geodesic_m.notna()
assert int(ok.sum())==lc["pieces"]
assert np.isclose(wet.loc[ok,"length_geodesic_m"].sum()/wet.loc[ok,"length"].sum(),lc["total_ratio"],rtol=1e-12)
extra=[{"scope":"testbed","gate":"Anaheim_and_endpoint_routing_regression","pass":True,"value":10,"limit":"10 existing tests passed; see routing_regression.json; not a combined assignment"},
       {"scope":"both","gate":"flood_depth_mask","pass":depth.max()<=9.144,"value":depth.max(),"limit":"maximum 9.144 m"},
       {"scope":"both","gate":"direct_damage_asset_consolidation","pass":True,"value":cost.sum(),"limit":"roads summed; bridges/tunnels max once per link; matches production total"}]
g=pd.concat([g,pd.DataFrame(extra)],ignore_index=True).drop_duplicates(["scope","arm","gate"],keep="last");g.to_csv(P/"decision_checks.csv",index=False)
# Additional fixed-support diagnostics by native road class and state.
groupmetrics=[]
for scope,pre in [("conus","n"),("harvey15","h")]:
    for arm,tag in [("control","c"),("gateway","g")]:
        for key in ["faf5_class","STATE"]:
            for val,z in roads0.groupby(key,dropna=False):
                a=z[z.official.notna() & z[pre+"_"+tag+"_flow"].notna()]
                v=a[pre+"_"+tag+"_flow"]
                den=a.official.sum()
                correlation=v.corr(a.official) if v.nunique()>1 and a.official.nunique()>1 else np.nan
                groupmetrics.append({"scope":scope,"arm":arm,"group_key":key,"group":val,"links_compared":len(a),"missing_official":int(z.official.isna().sum()),"pearson":correlation,"wape":(v-a.official).abs().sum()/den if den else np.nan,"official_link_traversals":den,"modeled_link_traversals":v.sum()})
pd.DataFrame(groupmetrics).to_csv(P/"road_agreement_by_class_and_state.csv",index=False)
# The paired recovery export excludes isolated trips. Add intact baseline routes
# for a separate deterministic sample of those lost-service OD pairs.
from shapely.geometry import MultiLineString
cons=gpd.read_file(P/"CSG_review.gpkg",layer="connectors_baseline_comparison")
cons.e_id=cons.e_id.astype(str)
edgegeoms=pd.concat([roads0[["e_id","geometry"]],cons[["e_id","geometry"]]]).set_index("e_id").geometry.to_dict()
nodecent=gpd.read_file(P/"CSG_review.gpkg",layer="centroid_loading_comparison")
ref=Path("C:/Users/akothaw/Desktop/ResiFlow/faf5_2022_assignment_review.gpkg")
nearest=pyogrio.read_dataframe(ref,layer="faf5_centroids_near_gateway_features")
nearcols=nearest.drop(columns=["geometry","group","flow_status","all_tot_trips_day"])
nodecent=nodecent.drop(columns=[c for c in nearcols if c!="centroid_id"],errors="ignore").merge(nearcols,on="centroid_id",how="left",validate="one_to_one")
nodecent["facility_match_basis"]=np.where(nodecent.Facility_Name.notna(),"nearest native reference; proximity association, not facility OD evidence",None)
nodecent["county_fips_text"]=nodecent.county_fips.map(lambda x:f"{int(x):05}" if pd.notna(x) else None)
counties=pyogrio.read_dataframe(ref,layer="tiger_counties").to_crs(nodecent.crs)
host=gpd.sjoin(nodecent[["centroid_id","geometry"]],counties[["GEOID","NAME","geometry"]],how="left",predicate="within")
hostrows=[]
for cid,z in host.groupby("centroid_id"):
    candidates=sorted(z.GEOID.dropna().unique())
    hostrows.append({"centroid_id":cid,"host_county_fips":candidates[0] if len(candidates)==1 else None,"host_county_name":z.loc[z.GEOID.eq(candidates[0]),"NAME"].iloc[0] if len(candidates)==1 else None,"host_county_candidates":json.dumps(candidates),"host_county_status":"unique" if len(candidates)==1 else ("ambiguous" if candidates else "outside_polygons")})
hostfields=pd.DataFrame(hostrows)
nodecent=nodecent.drop(columns=[c for c in hostfields if c!="centroid_id"],errors="ignore").merge(hostfields,on="centroid_id",how="left",validate="one_to_one")
nodecent.to_file(P/"CSG_review.gpkg",layer="centroid_loading_comparison",driver="GPKG",index=False)
facilityrefs=pyogrio.read_dataframe(ref,layer="faf5_native_gateway_reference_points").to_crs(nodecent.crs)
facilityrefs.to_file(P/"CSG_review.gpkg",layer="native_facility_reference_points",driver="GPKG",index=False)
layers=pd.concat([layers,pd.DataFrame([{"layer":"native_facility_reference_points","features":len(facilityrefs)}])],ignore_index=True).drop_duplicates("layer",keep="last")
nodemap=nodecent.set_index(nodecent.centroid_node.astype(str)).centroid_id.to_dict()
ctcross=pd.read_csv(P/"retained_ct_road_nodes.csv")
ctcross.node_id=ctcross.node_id.astype(str)
ctcandidates=ctcross.groupby("node_id").county_fips.agg(lambda x:sorted(set(f"{int(v):05}" for v in x))).to_dict()
ctsingle={k:int(v[0]) for k,v in ctcandidates.items() if len(v)==1}
ctpoints=gpd.read_parquet(P/"ct_retained_road_nodes.gpq").to_crs(nodecent.crs)
ctpoints["county_candidates"]=ctpoints.node_id.map(lambda n:json.dumps(ctcandidates[str(n)]))
ctpoints["county_fips_text"]=ctpoints.node_id.map(lambda n:ctcandidates[str(n)][0] if len(ctcandidates[str(n)])==1 else None)
ctpoints["kind"]="R_ct_retained"
ctpoints.to_file(P/"CSG_review.gpkg",layer="ct_retained_road_loading_points",driver="GPKG",index=False)
layers=pd.concat([layers,pd.DataFrame([{"layer":"ct_retained_road_loading_points","features":len(ctpoints)}])],ignore_index=True).drop_duplicates("layer",keep="last")
loading=[];concentration=[]
for scope,pre in [("conus","n"),("harvey15","h")]:
    for arm,tag in [("control","c"),("gateway","g")]:
        for kind,z in nodecent.groupby("kind"):
            loads=z[pre+"_"+tag+"_out"]+z[pre+"_"+tag+"_in"]
            loading.append({"scope":scope,"arm":arm,"kind":kind,"inventory_centroids":len(z),"positive_out":int(z[pre+"_"+tag+"_out"].gt(0).sum()),"positive_in":int(z[pre+"_"+tag+"_in"].gt(0).sum()),"positive_either":int(loads.gt(0).sum()),"out_trips_day":z[pre+"_"+tag+"_out"].sum(),"in_trips_day":z[pre+"_"+tag+"_in"].sum()})
    z=nodecent[nodecent.kind.eq("G")].copy();z["endpoint_activity"]=z[pre+"_g_out"]+z[pre+"_g_in"]
    z=z.sort_values("endpoint_activity",ascending=False)
    for n in [1,3,10,25]:concentration.append({"scope":scope,"top_centroids":n,"gateway_endpoint_activity_day":z.head(n).endpoint_activity.sum(),"share_of_G_activity":z.head(n).endpoint_activity.sum()/z.endpoint_activity.sum()})
for arm,tag in [("control","c"),("gateway","g")]:
    for direction in ["out","in"]:
        actual=nodecent["n_"+tag+"_"+direction].sum()+ctpoints["n_"+tag+"_"+direction].sum()
        expected=b[(b.scope=="conus")&(b.arm==arm)].trips_day.iloc[0]
        assert np.isclose(actual,expected,rtol=1e-9)
    loading.append({"scope":"conus","arm":arm,"kind":"R_ct_retained","inventory_centroids":len(ctpoints),"positive_out":int(ctpoints["n_"+tag+"_out"].gt(0).sum()),"positive_in":int(ctpoints["n_"+tag+"_in"].gt(0).sum()),"positive_either":int((ctpoints["n_"+tag+"_out"]+ctpoints["n_"+tag+"_in"]).gt(0).sum()),"out_trips_day":ctpoints["n_"+tag+"_out"].sum(),"in_trips_day":ctpoints["n_"+tag+"_in"].sum()})
pd.DataFrame(loading).to_csv(P/"centroid_loading_by_group.csv",index=False)
pd.DataFrame(concentration).to_csv(P/"gateway_concentration.csv",index=False)
profiles=[]
for pf in sorted(P.glob("*_profile.tsv")):
    pp=pd.read_csv(pf,sep="\t");pp.insert(0,"run",pf.stem.removesuffix("_profile"));profiles.append(pp)
prof=pd.concat(profiles,ignore_index=True)
prof.to_csv(P/"profiling_all_stages.csv",index=False)
extras=[]
for path in sorted(P.glob("*_d0_isolated_baseline_paths.pq")):
    rows=pd.read_parquet(path);output=[]
    for row in rows.to_dict("records"):
        edgeids=list(row.pop("path"));segments=[]
        for eid in edgeids:
            shape=edgegeoms[str(eid)]
            if shape.geom_type=="LineString":segments.append(list(shape.coords))
            else:segments.extend([list(part.coords) for part in shape.geoms])
        assert segments
        row["geometry"]=MultiLineString(segments);row["edge_ids_json"]=json.dumps(edgeids,separators=(",",":"))
        row["origin_centroid_id"]=nodemap.get(str(row["origin_node"]))
        row["destination_centroid_id"]=nodemap.get(str(row["destination_node"]))
        row["state"]="intact_route_for_isolated_OD";row["day"]=0
        output.append(row)
    gg=gpd.GeoDataFrame(output,geometry="geometry",crs=roads0.crs)
    gg.to_file(P/"CSG_review.gpkg",layer=path.stem,driver="GPKG",index=False)
    extras.append({"layer":path.stem,"features":len(gg)})
    sm=pd.read_csv(P/"path_sample_manifest.csv")
    sm=pd.concat([sm,pd.DataFrame([{"layer":path.stem,"sample_paths":len(gg),"missing_geometry_edges":0}])],ignore_index=True).drop_duplicates("layer",keep="last")
    sm.to_csv(P/"path_sample_manifest.csv",index=False)
layers=pd.concat([layers,pd.DataFrame(extras)],ignore_index=True).drop_duplicates("layer",keep="last")
layers.to_csv(P/"gis_layers.csv",index=False)
sizing=[];budget_summary=[]
for scope in ["conus","harvey15"]:
    pre=json.loads((P/(scope+"_preflight.json")).read_text())
    conservation=pd.read_csv(P/(scope+"_conservation.csv"))
    for trade,market in [(2,"import"),(3,"export")]:
        volume=conservation.loc[conservation.trade_type.eq(trade),"base"].sum()
        sizing.append({"scope":scope,"market":market,"eligible_trips_day":volume,"share_of_total":volume/pre["trips_day"]})
    bud=pd.read_csv(P/(scope+"_gateway_budgets.csv"))
    bud["shortfall"]=bud.published_target-bud.allocated_trips
    bud["target_fraction"]=bud.allocated_trips/bud.published_target
    bud.to_csv(P/(scope+"_gateway_target_shortfalls.csv"),index=False)
    for market,z in bud.groupby("market"):
        budget_summary.append({"scope":scope,"market":market,"target_trips_day":z.published_target.sum(),"allocated_trips_day":z.allocated_trips.sum(),"shortfall_trips_day":z.shortfall.sum(),"capped_gateway_directions":int(z.shortfall.gt(1e-7).sum())})
sizing=pd.DataFrame(sizing);sizing.to_csv(P/"eligible_import_export_sizing.csv",index=False)
bud=pd.DataFrame(budget_summary);bud.to_csv(P/"gateway_target_summary.csv",index=False)
# Independent source checks and cohort-specific interpretation.
recdiff=[]
for scope,z in r.groupby("scope"):
    a=z[z.arm.eq("control")].set_index("event_day")
    v=z[z.arm.eq("gateway")].set_index("event_day")
    for day in a.index:
        row={"scope":scope,"day":int(day)}
        for col in ["total_disrupted_flow","isolated_flow_total","rerouting_cost","direct_damage_total_usd"]:
            row[col+"_control"]=a.loc[day,col];row[col+"_gateway"]=v.loc[day,col]
            row[col+"_delta"]=v.loc[day,col]-a.loc[day,col]
        row["isolation_share_of_total_control"]=a.loc[day,"isolated_flow_total"]/b[(b.scope==scope)&(b.arm=="control")].trips_day.iloc[0]
        row["isolation_share_of_total_gateway"]=v.loc[day,"isolated_flow_total"]/b[(b.scope==scope)&(b.arm=="gateway")].trips_day.iloc[0]
        recdiff.append(row)
rd=pd.DataFrame(recdiff);rd.to_csv(P/"recovery_control_gateway_differences.csv",index=False)
assert (pc.post_flow_on_changed_paths>=-1e-7).all()
pc["post_flow_on_changed_paths"]=pc.post_flow_on_changed_paths.clip(lower=0)
pc["changed_share_of_successfully_routed_flow"]=pc.post_flow_on_changed_paths/pc.post_flow.replace(0,np.nan)
pc.to_csv(P/"all_path_change_statistics.csv",index=False)
# C and S county attribution is exact from published ID convention. G remains NA:
# host facility county is not the original county of displaced demand.
iso=[]
for f in sorted(P.glob("*_isolation_raw_day*.pq")):
    raw=pd.read_parquet(f)
    scope="harvey15" if f.stem.startswith("harvey15") else "conus"
    arm="gateway" if "_gateway_" in f.stem else "control"
    day=int(f.stem.split("_day")[1])
    for direction,key in [("origin","origin_node"),("destination","destination_node")]:
        x=raw[[key,"flow"]].copy();x["centroid_id"]=x[key].astype(str).map(nodemap)
        ct=x[key].astype(str).isin(ctcandidates)
        assert (x.centroid_id.notna()|ct).all()
        x["kind"]=np.select([x.centroid_id.ge(1000000),x.centroid_id.between(100005,100411)],["S","G"],default="C")
        x.loc[ct,"kind"]="R_ct_retained"
        x["county_fips"]=np.where(x.kind.eq("C"),x.centroid_id,np.where(x.kind.eq("S"),x.centroid_id//1000,np.nan))
        x.loc[ct,"county_fips"]=x.loc[ct,key].astype(str).map(ctsingle)
        x["county_group"]=x.county_fips.map(lambda v:f"{int(v):05}" if pd.notna(v) else "NA_gateway")
        shared=ct&x.county_fips.isna()
        x.loc[shared,"county_group"]=x.loc[shared,key].astype(str).map(lambda n:"CT_shared_"+"_".join(ctcandidates[n]))
        y=x.groupby(["county_group","kind"],as_index=False).flow.sum()
        y["scope"]=scope;y["arm"]=arm;y["day"]=day;y["direction"]=direction
        iso.append(y)
iso=pd.concat(iso,ignore_index=True)
iso.to_csv(P/"isolation_by_county_and_node_group.csv",index=False)
countyview=counties.copy()
for scope,pre in [("conus","n"),("harvey15","h")]:
    for arm,tag in [("control","c"),("gateway","g")]:
        for day in [0,7]:
            for direction,end in [("origin","out"),("destination","in")]:
                z=iso[(iso.scope==scope)&(iso.arm==arm)&(iso.day==day)&(iso.direction==direction)&iso.county_group.ne("NA_gateway")].groupby("county_group").flow.sum()
                countyview[f"{pre}_{tag}_d{day}_{end}"]=countyview.GEOID.map(z).fillna(0)
countyview.to_file(P/"CSG_review.gpkg",layer="county_isolation_comparison",driver="GPKG",index=False)
layers=pd.concat([layers,pd.DataFrame([{"layer":"county_isolation_comparison","features":len(countyview)}])],ignore_index=True).drop_duplicates("layer",keep="last")
layers.to_csv(P/"gis_layers.csv",index=False)
# Cost and route comparisons for identical selected OD pairs, attributes only.
samplecost=[]
for name in layers.layer:
    if not name.endswith("_pre_paths"):continue
    postname=name.replace("_pre_paths","_post_paths")
    preattrs=pyogrio.read_dataframe(P/"CSG_review.gpkg",layer=name,read_geometry=False)
    postattrs=pyogrio.read_dataframe(P/"CSG_review.gpkg",layer=postname,read_geometry=False)
    def paircost(x):
        x=x.copy();x["trip_cost"]=x.flow*(x.operating_cost_per_flow+x.time_cost_per_flow+x.toll_cost_per_flow+x.fare_cost_per_flow)
        return x.groupby(["origin_node","destination_node"]).agg(flow=("flow","sum"),cost=("trip_cost","sum"),paths=("edge_ids_json",lambda s:tuple(sorted(s))))
    a=paircost(preattrs);z=paircost(postattrs)
    q=a.merge(z,left_index=True,right_index=True,how="outer",suffixes=("_intact","_recovery"))
    q["delta_cost_usd"]=q.cost_recovery-q.cost_intact
    q["route_changed"]=q.paths_intact!=q.paths_recovery
    q=q.drop(columns=["paths_intact","paths_recovery"]).reset_index()
    q["path_layer_prefix"]=name.removesuffix("_pre_paths")
    q.to_csv(P/(name.removesuffix("_pre_paths")+"_sample_od_changes.csv"),index=False)
    samplecost.append(q)
pd.concat(samplecost,ignore_index=True).sort_values("delta_cost_usd",ascending=False).to_csv(P/"sample_od_cost_changes.csv",index=False)
# QGIS project with relative GeoPackage sources. Useful in QGIS; ArcGIS can open GPKG directly.
root=ET.Element("qgis",version="3.34.0",projectname="C+S+G freight review")
ET.SubElement(root,"title").text="C+S+G freight review — CONUS and Harvey-15"
projectcrs=ET.SubElement(root,"projectCrs");sp=ET.SubElement(projectcrs,"spatialrefsys")
for key,value in [("authid","EPSG:4326"),("description","WGS 84"),("projectionacronym","longlat"),("ellipsoidacronym","EPSG:7030")]:ET.SubElement(sp,key).text=value
tree=ET.SubElement(root,"layer-tree-group",name="",checked="Qt::Checked",expanded="1")
pl=ET.SubElement(root,"projectlayers")
# Put paths and point layers above the road layer.
names=[n for n in layers.layer if "paths" in n]+["centroid_loading_comparison","ct_retained_road_loading_points","native_facility_reference_points","connectors_baseline_comparison","harvey_flood_damage_links","harvey_all_wet_links"]+[n for n in layers.layer if "isolation" in n]+[n for n in layers.layer if "cohort_edges" in n]+["roads_baseline_comparison"]
for i,name in enumerate(names):
    info=pyogrio.read_info(P/"CSG_review.gpkg",layer=name)
    lid=name+"_"+str(i)
    checked=name in ["roads_baseline_comparison","connectors_baseline_comparison","centroid_loading_comparison","n_g_baseline_paths"]
    ET.SubElement(tree,"layer-tree-layer",id=lid,name=name,source="./CSG_review.gpkg|layername="+name,providerKey="ogr",checked="Qt::Checked" if checked else "Qt::Unchecked",expanded="0")
    point="Point" in info["geometry_type"];poly="Polygon" in info["geometry_type"]
    ml=ET.SubElement(pl,"maplayer",type="vector",geometry="Point" if point else ("Polygon" if poly else "Line"),hasScaleBasedVisibilityFlag="0")
    ET.SubElement(ml,"id").text=lid;ET.SubElement(ml,"layername").text=name
    ET.SubElement(ml,"datasource").text="./CSG_review.gpkg|layername="+name
    ET.SubElement(ml,"provider",encoding="UTF-8").text="ogr"
    ET.SubElement(ml,"subsetstring").text="kind = 'G'" if name=="centroid_loading_comparison" else ""
    renderer=ET.SubElement(ml,"renderer-v2",type="singleSymbol",symbollevels="0",forceraster="0")
    syms=ET.SubElement(renderer,"symbols")
    sym=ET.SubElement(syms,"symbol",type="marker" if point else ("fill" if poly else "line"),name="0",alpha="0.8",clip_to_extent="1")
    sl=ET.SubElement(sym,"layer",**{"class":"SimpleMarker" if point else ("SimpleFill" if poly else "SimpleLine"),"enabled":"1","locked":"0","pass":"0"})
    color="100,56,160,255" if point or "connectors" in name else ("190,70,24,255" if "paths" in name else ("50,110,175,255" if "cohort" in name else "170,177,184,255"))
    props={"color":color,"name":"circle","size":"2.6","outline_color":"255,255,255,255"} if point else {"line_color":color,"line_width":"0.45" if "paths" in name else ("0.35" if "connectors" in name else "0.12"),"line_style":"solid"}
    if poly:props={"color":"210,218,225,80","outline_color":"130,145,155,255","outline_width":"0.1"}
    for k,v in props.items():ET.SubElement(sl,"prop",k=k,v=v)
canvas=ET.SubElement(root,"mapcanvas")
extent=ET.SubElement(canvas,"extent")
for k,v in [("xmin",-96.2),("ymin",28.6),("xmax",-94.5),("ymax",30.6)]:ET.SubElement(extent,k).text=str(v)
ET.SubElement(canvas,"rotation").text="0"
ET.ElementTree(root).write(P/"CSG_review.qgs",encoding="utf-8",xml_declaration=True)
ET.parse(P/"CSG_review.qgs")
with sqlite3.connect(P/"CSG_review.gpkg") as con:
    assert con.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
for row in layers.to_dict("records"):
    assert pyogrio.read_info(P/"CSG_review.gpkg",layer=row["layer"])["features"]==int(row["features"])
manifest["layers"]=layers.to_dict("records")
manifest["checks_all_pass"]=bool(g["pass"].astype(str).str.lower().eq("true").all())
manifest["gis_integrity"]="passed after local enrichment"
(P/"manifest.json").write_text(json.dumps(manifest,indent=2))
# Static route maps with local vector geometry, no web basemap dependency.
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
roads=roads0
if roads.crs.to_epsg()!=4326:roads=roads.to_crs(4326)
cent=gpd.read_file(P/"CSG_review.gpkg",layer="centroid_loading_comparison").to_crs(4326)
paths=gpd.read_file(P/"CSG_review.gpkg",layer="n_g_baseline_paths").to_crs(4326)
fig,axs=plt.subplots(1,2,figsize=(14,6))
for ax,(title,bounds) in zip(axs,[("LA / Long Beach",(-118.65,33.55,-117.8,34.12)),("Houston",(-95.7,29.35,-94.75,30.15))]):
    x0,y0,x1,y1=bounds
    roads.cx[x0:x1,y0:y1].plot(ax=ax,color="#c0c4c7",linewidth=.35)
    paths.cx[x0:x1,y0:y1].plot(ax=ax,color="#ba4718",linewidth=.9,alpha=.55)
    cs=cent[cent.kind.eq("G")].cx[x0:x1,y0:y1]
    cs.plot(ax=ax,color="#6336a0",markersize=18,zorder=5)
    for _,v in cs.iterrows():ax.annotate(str(int(v.centroid_id)),(v.geometry.x,v.geometry.y),fontsize=7,xytext=(3,3),textcoords="offset points")
    ax.set_xlim(x0,x1);ax.set_ylim(y0,y1);ax.set_title(title);ax.set_xlabel("Longitude (degrees)");ax.set_ylabel("Latitude (degrees)")
fig.suptitle("Selected actual C+S+G baseline freight routes\nOrange: routed paths; purple: official facility-range centroids; gray: physical roads",fontsize=12)
fig.text(.01,.01,"Source: full-CONUS run, 2026-11-17. Deterministic review sample; line counts are not total demand. No web basemap.",fontsize=9)
fig.tight_layout(rect=(0,.04,1,.90));fig.savefig(P/"route_preview.png",dpi=160);plt.close(fig)
readme="""# C+S+G freight GIS review
Open **CSG_review.gpkg** in ArcGIS Pro or QGIS. The optional **CSG_review.qgs** opens a styled project initially over Houston.
Open **DECISION_REPORT.html** for statistics and the sealing assessment. All layers are local; no web service is required.

## Start here
1. Load centroid_loading_comparison, connectors_baseline_comparison and roads_baseline_comparison.
2. Filter kind='G' for gateways. Label centroid_id (official ID); centroid_node is the separate ResiFlow solver ID.
3. In n_g_baseline_paths select origin_centroid_id=100146 for Houston, 100174 for Long Beach, or 100178 for LA Harbor. Each feature contains actual routed physical and connector edges.
4. Compare n_g_d0_pre_paths with n_g_d0_post_paths for the SAME selected OD pairs on the intact and damaged network. Day-7 and day-90 layers work identically. Use n_c_* for the C+S control and h_* for Harvey-15.
   Join n_g_d0_sample_od_changes.csv on origin_node and destination_node for paired flow, cost and route-change attributes. Equivalent CSVs exist for every reviewed arm/day. sample_od_cost_changes.csv ranks changes within the review sample, not all national OD pairs.
5. Inspect *_d0_isolated_baseline_paths for intact routes of selected OD pairs that lose service. isolated_flow is the lost trucks/day; flow is the original intact path flow and can be larger for partially isolated pairs. These routes are intentionally absent from the paired recovery exports.
6. Inspect harvey_all_wet_links, harvey_flood_damage_links, day-0 isolation point layers, and *_cohort_edges for recovery effects.

## Fields and units
n = full CONUS, h = Harvey-15; c = mean-parent C+S control, g = C+S+G.
*_flow = assigned link traversals in trucks/day; *_out and *_in = OD origin and destination trip totals, separately. Adding origins and destinations counts each trip twice.
*_delta_flow = gateway minus control baseline traversals.
official = published FAF22 modeled link trips/day; missing_record remains NA, separate from explicit zero.
all_out/all_in and market-specific centroid columns = official directional connector traversals, NOT an independently observed OD matrix.
county_fips identifies the parent county for C and S. G is NA because its original county demand cannot be inferred from facility ID. Isolation county summaries therefore retain NA_gateway separately.
host_county_fips is a spatial overlay of the centroid location on TIGER counties; it is NOT the original county of displaced demand. Offshore or boundary-exterior points may have NA. County isolation polygons aggregate C+S only; G is retained separately in centroid and isolation tables.
Connecticut exception: nine newer planning-region keys lack exact official parent-centroid IDs and retain eight original road loading nodes in both CONUS arms. ct_retained_road_loading_points shows them. Node 312022 is shared by 09120 and 09190; its county cannot be recovered uniquely from the aggregated node OD, so isolation is retained in CT_shared_09120_09190 rather than split arbitrarily. Unique CT road-node county totals are included in county polygons; the shared bucket and G remain separate.
Facility_Name/Type and nearby_facility_node_id preserve the earlier nearest-reference association. They are proximity labels, not proof of facility-level OD. native_facility_reference_points contains the underlying 1,036 native FAF reference locations for spot checks.
path flow = realised trucks/day. edge_ids_json preserves the ordered edge-ID sequence. Route geometry is a MultiLineString of those exact links, including synthetic connectors; no straight-line OD substitutes.
Native link geometry orientation is retained; use OD origin/destination and edge_ids_json for travel direction rather than assuming every geometry part points in the direction of travel.
Costs are the model's reported dollars. Rerouting is incremental relative to the intact comparison cohort. Do not sum the six sampled recovery days and call that an integrated event total.
isolation_cost and isolation_cost_usd are ALTERNATIVE valuations: the former uses the model time-value calculation, the latter uses $50 per isolated trip-day. They must not be added together.
direct damage is physical-network damage, shared across demand variants. It is repeated per recovery day in source tables and must not be summed across days.

## Coverage and path sampling
Road and connector baseline layers cover the complete saved graph; statistics use all positive paths.
Individual route features are a review SAMPLE, selected deterministically as the 250 largest-flow path IDs plus the largest-flow path at every loaded gateway origin and gateway destination. Recovery samples select OD pairs from that day's intact comparison export, then retain every realised pre/post path for those selected pairs.
The same OD cohort is paired WITHIN each arm and day. C+S and C+S+G have different endpoint sets, and cannot be joined by od_id or interpreted as identical OD pairs across arms.
The separate isolated-route sample takes the 250 largest isolated OD flows plus the largest isolated OD at every affected G origin and G destination. See path_sample_manifest.csv and gis_layers.csv for actual sample counts. Full path Parquets remain on Hopper; their absolute locations are recorded in provenance.json. No path-edge geometry was missing in exported features.
*_cohort_edges aggregate ALL exported disrupted-cohort paths, not the selected route sample. base_cohort_flow/post_cohort_flow are cohort-specific volumes, NOT total network traffic. Recovery cohorts can differ across arms; compare recovery shares as well as absolute volumes.
Days 0, 7 and 90 have spatial path/edge layers; all six days (0,7,14,30,60,90) have complete statistics. Full source-day tables are on Hopper.

## Review priorities
Check Houston 100146, LA Harbor 100178 and Long Beach 100174, then gateways with the largest target shortfalls or highest access-road V/C.
The freight-only mechanics can be frozen if their gates pass. Combined passenger+freight access capacity, missing-flow sensitivity, payload/trip-generation differences and independent facility OD validation remain separate limitations. Published connector flows were used in allocation, so close connector agreement is partly built in.
Do not adjust allocation to make Harvey damage or isolation smaller.
"""
(P/"README.md").write_text(readme,encoding="utf-8")
def table(frame):return frame.to_html(index=False,float_format=lambda x:f"{x:,.6g}",border=0,escape=True)
passed=g["pass"].astype(str).str.lower().eq("true").all()
title="C+S+G mechanics pass; agreement is mixed; freeze the freight variant, hold combined acceptance" if passed else "Hold sealing: one or more mechanical checks failed"
reasons="""The baseline tests isolate endpoint allocation: identical physical capacities and freight totals, mean weight for missing parent flow, and endpoint-only access. Both scopes deliver the full baseline demand. This is an all-or-nothing comparison at the tested freight load, not evidence of improved convergence under congestion.
Full CONUS refers to the saved corrected routable inter-county freight OD, with original same-node pairs excluded. Harvey-15 uses a subset of OD counties while retaining the national network; it is not a road-network clip. Both arms restore the same 3,795 connectors. The common physical solver graph has 483,442 roads; 157 native road IDs are outside that solver support. Missing published flow records stay NA.
The declared Connecticut exception is unchanged: nine planning regions without exact official parent IDs retain eight road loading points. One point serves two regions, so node-level isolation cannot be assigned uniquely between those two. The GIS supplies these road points and keeps the shared county bucket explicit. This variant is not a claim that every county has been converted to an official parent centroid.
Gateway flows redistribute existing freight. They do not recover Caliper's facility OD matrix. The allocation preserves zone-pair/commodity/market totals and caps gateway activity to available eligible demand. Consequently, a target shortfall is a documented scope/model mismatch, not a reason to create extra trips.
Treat sealing as freezing this freight variant, its inputs, and assumptions. Final combined-network acceptance requires the passenger+freight binding-link check. Keep zeros and missing records separate, and keep parent-mean as the declared default rather than selecting it by fit.
The published-assignment comparison uses common physical link IDs, includes explicit zeros, and excludes missing official values from scores while counting them. National road-link sums count traversals, not trip generation. ResiFlow's flat 20-ton payload and single least-cost first-pass routing differ from the documented FAF assignment's payload and path-choice methods. Residual volume bias cannot be attributed to connectors alone."""
body=f"""<h1>{html.escape(title)}</h1><p>Matched freight-only full-CONUS and Harvey-15 C+S control versus C+S+G. Scenario 304 / recovery scenario 1. Generated 2026-11-17.</p><p>{html.escape(reasons).replace(chr(10),'</p><p>')}</p>
<h2>Decision gates</h2><p>Conservation: 1e-9 relative tolerance. Haul: ±2% relative to the matched C+S control. Shortcuts: exactly zero. Baseline delivery: all trips within 1e-9. Physical capacity equality: exact; numerical exceedance tolerance 1e-6. These are predeclared mechanics checks, not fitted targets. Road agreement and hazard outcomes are diagnostic.</p>{table(g)}
<h2>Baseline demand and haul</h2>{table(b)}
<h2>Eligible existing import/export demand</h2><p>Computed from reconstructed in-scope inter-county cells. This is the portion eligible for gateway reassignment, not all international freight in the national FAF publication. Import and export are mutually exclusive markets.</p>{table(sizing)}
<h2>Gateway target caps and loading coverage</h2><p>Published directional activity versus the allocated eligible demand. Target shortfalls remain explicit. Outbound and inbound demand are separate views of the same trips; do not add national totals across ends. Gateway concentration uses combined endpoint activity as its denominator.</p>{table(bud)}{table(pd.DataFrame(loading))}{table(pd.DataFrame(concentration))}
<h2>Road-link agreement with FAF22</h2><p>Same physical-link support; official zeros included, missing records excluded from scores. WAPE is sum absolute error divided by sum official link flows. Correlation describes spatial pattern; it does not validate volume or trip generation. Harvey-15 is a demand subset on the national graph, so its score against full FAF22 is not like-for-like.</p>{table(m)}
<p>Clinical reading: CONUS correlation increases 0.5794 → 0.5842, but WAPE improves only 1.1076 → 1.1055. LA WAPE improves 0.9309 → 0.8571; Harris WAPE worsens 0.9403 → 0.9867 despite higher correlation. Matched-link traversal excess rises 25.7% → 26.8%. Thus endpoint loading improves some spatial patterns, while absolute volume and route-distribution disagreement remain. Inspect n_delta_abs_error on the roads layer: positive means worse agreement. The top increases and decreases and functional-class breakdowns are provided as separate CSVs. Do not tune endpoint shares to minimize these scores.</p>{table(error_parts)}
<p>Harris diagnosis: on the two matched gateway-access roads, absolute error improves by 9,289 summed link traversals/day. Other matched Harris roads worsen by 176,225; HPMS F1 roads account for +193,899 before offsets from other classes. Several largest increases form an I-610 chain: links 642076, 642090, 641808, 641804 and 641802 each gain about 3,895 trucks/day. For link 642076, the model rises from 6,830 to 10,725 versus FAF22's 4,631. This localizes the disagreement downstream of access. It supports a route/destination-distribution investigation rather than claiming a disconnected or capacity-bound gateway; it does not identify a unique causal parameter.</p>
<h2>Harvey recovery: gateway minus control</h2><p>Flows are trucks/day at the specified recovery snapshot. Both arms have the same direct physical damage. Effects reflect changed demand locations and routes, not a changed hazard.</p>{table(rd)}
<h2>Actual path changes: all exported paths</h2><p>Exact ordered edge lists are compared within each arm/day. Unchanged flow is the minimum overlapping flow on identical endpoint/path combinations. Changed share uses successfully rerouted flow as denominator. The paired intact export excludes isolated trips. Isolation is reported separately, and selected lost-service routes are supplied in separate *_d0_isolated_baseline_paths layers.</p>{table(pc)}
<h2>Damage and complete flood checks</h2><p>Whole bridges and tunnels are counted once per link; road cell pieces are summed. Damage-bearing pieces alone are insufficient to count all wet links, so the complete stage-2 intersection table is used for depth and class statistics. Length-check pieces are those at least 1 m long. Geodesic/projected total ratio: {lc['total_ratio']:.9f}; p01/p50/p99: {lc['ratio_p01']:.6f} / {lc['ratio_p50']:.6f} / {lc['ratio_p99']:.6f}.</p>{table(da)}{table(depthstats)}{table(floodstats)}
<h2>Review maps and package contents</h2><img src="route_preview.png" alt="Selected baseline freight routes around LA and Houston"><p>See README.md for layer meanings, sample selection, paired-path review, costs and limits.</p>{table(layers)}
<h2>Profiling and job bookkeeping</h2><p>All source runs were profiled; complete per-stage data are in profiling_all_stages.csv. Baseline jobs 3784302 and 3784306 completed assignment but failed their initial follow-up verifier path. Their saved assignments were subsequently revalidated; successful replacement recovery jobs were 3787728 and 3787729. No failed assignment artifact is being treated as an unchecked success.</p>{table(prof[prof.label.str.contains('stage1|stage4')])}
<h2>Evidence and reproducibility</h2><p>See provenance.json, decision_checks.csv, preserved shortcut audit logs, gateway budgets and coverage manifests, path_sample_manifest.csv, and export_csg_gis_review.py. GeoPackage SQLite integrity and layer counts were checked after export and after transfer.</p>"""
css="body{font:15px/1.5 system-ui,sans-serif;max-width:1400px;margin:32px auto;padding:0 24px;color:#18232c}h1{font-size:26px}h2{margin-top:36px}table{display:block;overflow:auto;border-collapse:collapse;max-width:100%;font-size:12px}th,td{padding:7px 10px;border-bottom:1px solid #d9dfe4;text-align:right;white-space:nowrap}th{background:#edf1f4}img{max-width:100%}p{max-width:1100px}"
(P/"DECISION_REPORT.html").write_text('<!doctype html><html><head><meta charset="utf-8"><title>C+S+G decision review</title><style>'+css+'</style></head><body>'+body+'</body></html>',encoding="utf-8")
with (P/"CSG_review.gpkg").open("rb") as fh:gis_hash=hashlib.file_digest(fh,"sha256").hexdigest()
provenance={"date":"2026-11-17","source_root":manifest["source_root"],"baseline_jobs":{"harvey15_control":3784300,"harvey15_gateway":3784302,"conus_control":3784304,"conus_gateway":3784306},"recovery_jobs":{"harvey15_control":3784301,"harvey15_gateway":3787728,"conus_control":3784305,"conus_gateway":3787729},"compute_export_job":3790925,"isolated_route_export_job":3790999,"source_code_commit":"19b02b1","full_paths":"/scratch/akothaw/multimodal_hazard_data/results/{scope}_connector_test2g_{arm}/odpfc_parts/*.pq","full_recovery_paths":"/scratch/akothaw/multimodal_hazard_data/results/rerouting_analysis/{scope}_connector_test2g_{arm}/304/1/odpfc_freight_s1_day{day}{_baseline}.pq","export_script_sha256":hashlib.sha256((P/"export_csg_gis_review.py").read_bytes()).hexdigest(),"gis_sha256":gis_hash,"finalizer_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),"readback_validation":"SQLite integrity=ok; all reported feature counts checked"}
(P/"provenance.json").write_text(json.dumps(provenance,indent=2))
print(title);print(rd[["scope","day","isolated_flow_total_delta"]].to_string(index=False))
print("layer count",len(layers),"sample features",pd.read_csv(P/"path_sample_manifest.csv").sample_paths.sum())
