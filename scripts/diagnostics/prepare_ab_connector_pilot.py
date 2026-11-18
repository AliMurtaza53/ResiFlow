"""Prepare fixed-OD A/B networks for the preregistered five-county connector pilot."""
from pathlib import Path
import argparse,json,hashlib,time
import numpy as np
import pandas as pd
import geopandas as gpd
import pyogrio,duckdb
import shapely
from shapely.geometry import Point,LineString
from resiflow.networks.hazard_eligibility import centroid_connector_mask
from resiflow.networks.connector_pilot import AccessIndex

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,required=True);ap.add_argument("--reference",type=Path,required=True)
    ap.add_argument("--output",type=Path,required=True);a=ap.parse_args()
    out=a.output;out.mkdir(parents=True,exist_ok=False)
    root=a.root;inputdir=root/"stage2_scripts/connector_test1_inputs"
    raw=gpd.read_parquet(inputdir/"faf5_road_links.gpq")
    raw.e_id=raw.e_id.astype(str)
    raw[["from_id","to_id"]]=raw[["from_id","to_id"]].astype(str)
    baseline=gpd.read_parquet(root/"results/conus_connector_test2g_gateway/edge_flows.gpq",
        columns=["e_id","faf5_class","from_id","acc_flow","current_capacity","time_hr"])
    baseline.e_id=baseline.e_id.astype(str);baseline.from_id=baseline.from_id.astype(str)
    native_mask=centroid_connector_mask(raw)
    validids=set(baseline.loc[~centroid_connector_mask(baseline)&baseline.current_capacity.gt(.5),"e_id"])
    roads=raw[raw.e_id.isin(validids)].copy()
    nodes=gpd.read_parquet(root/"soge_clusters/networks/faf5/faf5_road_nodes.gpq").to_crs(raw.crs)
    nodes.node_id=nodes.node_id.astype(str)
    index=AccessIndex(roads,nodes)
    county=gpd.read_file(a.reference,layer="pilot_counties").to_crs(raw.crs)
    county.GEOID=county.GEOID.astype(str).str.zfill(5)
    polygons=county.set_index("GEOID").geometry.to_dict()
    target_counties=set(polygons)
    cross=pd.read_csv(inputdir/"connector_crosswalk.csv",dtype={"centroid_node":str,"road_node":str,"e_id":str})
    centres=gpd.read_file(a.reference,layer="faf5_centroids_2022").to_crs(raw.crs)
    centres=centres.merge(cross[["centroid_id","centroid_node"]].drop_duplicates(),on="centroid_id",validate="one_to_one")
    labels=gpd.read_file(a.reference,layer="faf5_centroids_near_gateway_features")
    facilities=gpd.read_file(a.reference,layer="faf5_native_gateway_reference_points").to_crs(raw.crs)
    official=pd.read_parquet(root/"stage2_scripts/connector_test2_conus/official_roads.pq")
    official["CTFIPS"]=pd.to_numeric(official.CTFIPS,errors="coerce")
    roadcounty=official.set_index(official.link_id.astype(str)).CTFIPS.to_dict()
    nodecounties={}
    for row in roads[["e_id","from_id","to_id"]].itertuples(index=False):
        fips=roadcounty.get(row.e_id)
        if pd.notna(fips):
            for n in (row.from_id,row.to_id):nodecounties.setdefault(n,set()).add(f"{int(fips):05}")
    records=[]
    for row in centres.itertuples():
        cid=int(row.centroid_id);kind="S" if cid>=1000000 else ("G" if 100005<=cid<=100411 else "C")
        fips=f"{cid//1000 if kind=='S' else cid:05}" if kind!="G" else None
        attribution="native_parent"
        if kind=="G":
            attached=set()
            for n in cross.loc[cross.centroid_id.eq(cid),"road_node"]:attached|=nodecounties.get(n,set())
            if len(attached)==1:fips=next(iter(attached));attribution="native_attachment_county"
            else:
                host=[k for k,p in polygons.items() if p.covers(row.geometry)]
                fips=host[0] if len(host)==1 else None;attribution="point_host_or_unresolved"
        records.append({"node_id":str(row.centroid_node),"centroid_id":cid,"kind":kind,"county_fips":fips,
                        "attribution":attribution,"geometry":row.geometry})
    registry=gpd.GeoDataFrame(records,geometry="geometry",crs=raw.crs)
    for cid,fips in {100174:"06037",100178:"06037",100146:"48201"}.items():
        assert registry.loc[registry.centroid_id.eq(cid),"county_fips"].iloc[0]==fips, "Reviewed gateway host county changed"
    # The already-corrected passenger OD and targets are reused without splitting demand again.
    pdir=root/"stage2_scripts/passenger_connected_fix/rebuilt"
    pax=pd.read_parquet(pdir/"passenger_conus_split_od.pq")
    pax[["origin_node","destination_node"]]=pax[["origin_node","destination_node"]].astype(str)
    oldtotal=float(pax.Car21.sum())
    cw=pd.read_csv(root/"code/ResiFlow_virtual_exemption_20261118/parameters/crosswalks/county_node_crosswalk_conterminous.csv",dtype=str)
    t=pd.read_csv(pdir/"node_targets.csv",dtype={"node":str,"target":str})
    rel=t.merge(cw[["node_id","county_fips"]],left_on="node",right_on="node_id",validate="many_to_many")
    origins=rel.groupby("target").county_fips.agg(lambda x:sorted(set(str(k).zfill(5) for k in x))).to_dict()
    used=set(pax.loc[pax.Car21.gt(0),"origin_node"])|set(pax.loc[pax.Car21.gt(0),"destination_node"])
    aliases={};alias_rows=[];alias_registry=[]
    template=raw[native_mask].iloc[0]
    for node,parents in sorted(origins.items()):
        if node not in used:continue
        fips=parents[0] if len(parents)==1 else None
        p=index.points.loc[node].geometry
        records.append({"node_id":node,"centroid_id":None,"kind":"P_road","county_fips":fips,"attribution":"passenger_targets" if fips else "shared_county_road",
                        "geometry":p})
        if fips not in target_counties:continue
        assert node in index.main
        alias=str(1900000000+int(node))
        assert alias not in set(raw.from_id)|set(raw.to_id)
        aliases[node]=alias
        q=Point(p.x+.001,p.y)
        parent_node=str(centres.loc[centres.centroid_id.eq(int(fips)),"centroid_node"].iloc[0])
        r=raw[native_mask&raw.from_id.eq(parent_node)].iloc[0].copy()
        r["e_id"]="pilot_pax_alias_"+node;r["from_id"]=alias;r["to_id"]=node
        r["geometry"]=LineString([q,p]);r["length"]=.001
        r["pilot_added_exit"]=False;r["pilot_role"]="passenger_endpoint_alias"
        alias_rows.append(r)
        alias_registry.append({"node_id":alias,"centroid_id":None,"kind":"P_alias","county_fips":fips,
                               "attribution":"unchanged_passenger_loading_point","geometry":q,"original_node":node})
    assert aliases
    for key in ["origin_node","destination_node"]:pax[key]=pax[key].replace(aliases)
    np.testing.assert_allclose(pax.Car21.sum(),oldtotal,rtol=1e-12,atol=0)
    pax.to_parquet(out/"passenger_fixed_od.pq",index=False)
    pd.DataFrame([{"original_node":k,"alias_node":v} for k,v in aliases.items()]).to_csv(out/"passenger_aliases.csv",index=False)
    registry=gpd.GeoDataFrame(records+alias_registry,geometry="geometry",crs=raw.crs).drop_duplicates("node_id")
    A=gpd.GeoDataFrame(pd.concat([raw,pd.DataFrame(alias_rows)],ignore_index=True),geometry="geometry",crs=raw.crs)
    A["pilot_added_exit"]=A.pilot_added_exit.fillna(False).astype(bool)
    conn=A[centroid_connector_mask(A)].copy()
    conmap=conn[["e_id","from_id","to_id"]].rename(columns={"from_id":"centroid_node","to_id":"road_node"})
    flow=baseline[centroid_connector_mask(baseline)].groupby("from_id").acc_flow.sum()
    positive=set(flow[flow.gt(0)].index)|set(aliases.values())
    units=registry[registry.county_fips.isin(target_counties)&registry.node_id.isin(positive)&registry.kind.isin(["C","S","G","P_alias"])]
    added=[];audit=[];summary=[]
    for unit in units.sort_values("node_id").itertuples():
        own=conn[conn.from_id.eq(unit.node_id)]
        assert not own.empty
        anchors=list(set(own.to_id)&index.main)
        facility_points=None
        if unit.kind=="G":
            label=labels[labels.centroid_id.eq(unit.centroid_id)]
            if len(label)==1:
                name=label.iloc[0].Facility_Name;typ=label.iloc[0].Facility_Type
                match=facilities[facilities.Facility_Name.eq(name)&facilities.Facility_Type.eq(typ)]
                facility_points=list(match.geometry)
            else:facility_points=[]
        chosen,checks=index.select(anchors,polygons[unit.county_fips],total=4,facility_points=facility_points)
        for row in checks:
            audit.append({**row,"unit_node":unit.node_id,"county_fips":unit.county_fips,"kind":unit.kind})
        for row in chosen:
            base=own[own.to_id.eq(row["anchor"])].iloc[0]
            new=base.copy();new["e_id"]=f"pilot_exit_{unit.node_id}_{row['selection_order']}"
            new["to_id"]=row["road_node"]
            new["geometry"]=index.access_geometry(base.geometry,row["anchor"],row["road_node"])
            new["length"]=new.geometry.length
            new["AB_FinalSpeed"]=new["BA_FinalSpeed"]=new["Speed_Limit"]=25.
            new["pilot_added_exit"]=True;new["pilot_role"]="area_access_estimate" if unit.kind!="G" else "same_facility_reference_access"
            new["pilot_selection_order"]=row["selection_order"];new["pilot_county"]=unit.county_fips
            new["pilot_access_path_m"]=row["access_path_m"]
            new["pilot_cost_geometry"]="native_access_plus_local_route_PROXY_not_new_physical_road"
            added.append(new)
        summary.append({"unit_node":unit.node_id,"county_fips":unit.county_fips,"kind":unit.kind,"native_valid_exits":len(anchors),
                        "added_exits":len(chosen),"total_valid_exits":len(anchors)+len(chosen),"reason":"screened" if chosen else "no_additional_credible_candidate"})
    B=gpd.GeoDataFrame(pd.concat([A,pd.DataFrame(added)],ignore_index=True),geometry="geometry",crs=raw.crs)
    B["pilot_added_exit"]=B.pilot_added_exit.fillna(False).astype(bool)
    assert A.e_id.is_unique and B.e_id.is_unique
    physicalA=A[~centroid_connector_mask(A)].reset_index(drop=True)
    physicalB=B[~centroid_connector_mask(B)].reindex(columns=A.columns).reset_index(drop=True)
    pd.testing.assert_frame_equal(physicalA,physicalB,check_dtype=False)
    A.to_parquet(out/"network_A.gpq",index=False);B.to_parquet(out/"network_B4.gpq",index=False)
    for arm,frame in [("A",A),("B4",B)]:
        frame[centroid_connector_mask(frame)][["e_id","from_id","to_id"]].rename(columns={"from_id":"centroid_node","to_id":"road_node"}).to_csv(out/f"connectors_{arm}.csv",index=False)
    registry.drop(columns="geometry").to_csv(out/"node_registry.csv",index=False)
    registry.to_file(out/"pilot_review.gpkg",layer="loading_units",driver="GPKG")
    pilotroads=roads[roads.e_id.map(roadcounty).map(lambda x:f"{int(x):05}" if pd.notna(x) else "").isin(target_counties)]
    pilotroads.to_file(out/"pilot_review.gpkg",layer="physical_roads",driver="GPKG")
    own_native=conn[conn.from_id.isin(units.node_id)]
    own_native.to_file(out/"pilot_review.gpkg",layer="existing_exits",driver="GPKG")
    if added:gpd.GeoDataFrame(added,geometry="geometry",crs=raw.crs).to_file(out/"pilot_review.gpkg",layer="added_exits",driver="GPKG")
    aud=pd.DataFrame(audit)
    if not aud.empty:
        aud=aud.replace([np.inf,-np.inf],np.nan)
        gpd.GeoDataFrame(aud,geometry=gpd.points_from_xy(aud.x,aud.y),crs=raw.crs).to_file(out/"pilot_review.gpkg",layer="candidate_audit",driver="GPKG")
    stats=pd.DataFrame(summary);stats.to_csv(out/"unit_coverage.csv",index=False)
    coverage=stats.groupby("county_fips").agg(positive_units=("unit_node","size"),modified_units=("added_exits",lambda x:int(x.gt(0).sum())),added_exits=("added_exits","sum")).reindex(sorted(target_counties)).fillna(0)
    coverage.to_csv(out/"county_coverage.csv")
    report={"passenger_trips":oldtotal,"freight_trips":1510749.5566692068,"physical_links_unchanged":len(physicalA),
            "new_aliases":len(alias_rows),"added_exits":len(added),"eligible_counties":sorted(target_counties),
            "coverage_pass":bool(coverage.modified_units.gt(0).all()),"same_OD_between_arms":True,
            "geometry_cost_assumption":"Added virtual geometry encodes native access plus a local routing-distance cost proxy; it does not claim a newly observed physical road. Physical cut edges and bridge/tunnel traversals cannot be bypassed."}
    (out/"preflight.json").write_text(json.dumps(report,indent=2))
    print(json.dumps(report,indent=2),flush=True)
    print(coverage.to_string(),flush=True)
    if not report["coverage_pass"]:raise ValueError("County coverage gate failed; do not freeze either arm")
    # Small declared path-time diagnostic, never used to choose candidates.
    from resiflow import road_revised as road
    db=duckdb.connect();db.execute("SET threads=4")
    freight=root/"stage2_scripts/connector_test2_gateway_full/conus/harvey15_gateway_od.pq"
    unitids=",".join("'"+str(n)+"'" for n in units.node_id if not str(n).startswith("1900"))
    pairs=db.execute("SELECT origin_node,destination_node,Car21 FROM read_parquet('"+str(freight)+"') WHERE CAST(origin_node AS VARCHAR) IN ("+unitids+") OR CAST(destination_node AS VARCHAR) IN ("+unitids+") ORDER BY Car21 DESC,origin_node,destination_node LIMIT 250").df()
    diagnostic=[]
    base_time=baseline.set_index("e_id").time_hr
    for k,speed in [(0,25),(2,25),(3,25),(4,25),(4,15)]:
        frame=A if k==0 else B[~B.pilot_added_exit|B.pilot_selection_order.le(k)].copy()
        frame=frame[frame.e_id.isin(validids)|centroid_connector_mask(frame)].copy()
        times=frame.e_id.map(base_time)
        missing=times.isna()
        times.loc[missing]=frame.loc[missing].geometry.length/1609.344/25.
        if speed!=25:
            extra=frame.pilot_added_exit
            times.loc[extra]=frame.loc[extra].geometry.length/1609.344/speed
        graph=__import__("igraph").Graph.TupleList(frame[["from_id","to_id"]].itertuples(index=False,name=None),directed=False)
        graph.es["weight"]=times.tolist()
        centers=set(frame.loc[centroid_connector_mask(frame),"from_id"])
        graph.vs["faf_centroid"]=[str(n) in centers for n in graph.vs["name"]]
        road._set_worker_network(graph)
        total=0.;trips=0.;shortcuts=0;unreachable=0
        for origin,rows in pairs.groupby("origin_node"):
            _,_,paths,flows=road.find_least_cost_path((int(origin),rows.destination_node.tolist(),rows.Car21.tolist()))
            for destination,path,flowvalue in zip(rows.destination_node,paths,flows):
                if not path:unreachable+=1;continue
                total+=float(times.iloc[path].sum())*flowvalue;trips+=flowvalue
                for edge in path:
                    r=frame.iloc[edge]
                    if str(r.from_id) in centers and r.faf5_class==50 and str(r.from_id) not in {str(origin),str(destination)}:shortcuts+=1
        assert shortcuts==0 and unreachable==0
        diagnostic.append({"variant":"A" if k==0 else f"B{k}_speed{speed}","sample_pairs":len(pairs),"sample_trips":trips,"mean_path_time_hr":total/trips,"centroid_shortcuts":shortcuts,"scope":"250 highest-flow pilot freight pairs; time-only AON; not capacity or isolation"})
    pd.DataFrame(diagnostic).to_csv(out/"screening_path_time_range.csv",index=False)

if __name__=="__main__":main()
