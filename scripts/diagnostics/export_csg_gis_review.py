"""Export matched C+S / C+S+G freight results for GIS review. Run on a compute node."""
from pathlib import Path
import json, sqlite3, re, shutil, hashlib
import numpy as np
import pandas as pd
import geopandas as gpd
import duckdb
from shapely.geometry import MultiLineString
R=Path("/scratch/akothaw/multimodal_hazard_data")
OPS=R/"stage2_scripts/connector_test2_gateway_full"
OUT=R/"stage2_scripts/gateway_gis_review_20261117"
OUT.mkdir(exist_ok=False)
GPKG=OUT/"CSG_review.gpkg"
db=duckdb.connect()
db.execute("SET threads=4")
db.execute("SET memory_limit='40GB'")
db.execute("SET temp_directory='"+str(OUT/"ducktmp")+"'")
manifest=[]; baseline_stats=[]; metrics=[]; recover=[]; changes=[]; sample_stats=[]; checks=[]
keys=pd.read_csv(R/"stage2_scripts/connector_test1_inputs/connector_crosswalk.csv")
keys[["e_id","centroid_node","road_node"]]=keys[["e_id","centroid_node","road_node"]].astype(str)
keynodes=keys[["centroid_id","centroid_node"]].drop_duplicates()
node_cid=keynodes.set_index("centroid_node").centroid_id.to_dict()
g_nodes=set(keynodes.loc[keynodes.centroid_id.between(100005,100411),"centroid_node"])
keys["kind"]=np.select([keys.centroid_id.ge(1000000),keys.centroid_id.between(100005,100411)],["S","G"],default="C")
def write(frame,layer):
    frame=frame.copy()
    for c in frame.columns:
        if c!="geometry" and frame[c].dtype=="object":
            frame[c]=frame[c].map(lambda x:json.dumps(x) if isinstance(x,(list,dict,np.ndarray)) else x)
    if frame.empty:
        print("empty omitted",layer,flush=True); return
    assert frame.geometry.notna().all(),layer
    frame.to_file(GPKG,layer=layer,driver="GPKG",index=False)
    manifest.append({"layer":layer,"features":len(frame)})
    print("wrote",layer,len(frame),flush=True)
def view(name,path):
    db.execute("CREATE OR REPLACE VIEW "+name+" AS SELECT * FROM read_parquet('"+str(path)+"')")
def sql(q):return db.execute(q).df()
edgecols=["e_id","from_id","to_id","geometry","length_mile","faf5_class","road_classification","road_bridge","STATE","County_Name","current_capacity","acc_flow"]
edges=gpd.read_parquet(R/"results/conus_connector_test2g_gateway/edge_flows.gpq",columns=edgecols)
edges["e_id"]=edges.e_id.astype(str)
for c in ["from_id","to_id"]: edges[c]=edges[c].astype(str)
crs=edges.crs
geom=edges.set_index("e_id").geometry.to_dict()
road=edges[~edges.faf5_class.eq(50).fillna(False)].copy()
conn=edges[edges.faf5_class.eq(50).fillna(False)].copy().merge(keys[["e_id","centroid_id","centroid_node","road_node","kind"]],on="e_id",validate="one_to_one")
cent=gpd.read_file(R/"stage2_scripts/faf5_connector_inputs.gpkg",layer="faf5_centroids_2022").to_crs(crs).merge(keynodes,on="centroid_id",validate="one_to_one")
cent["kind"]=np.select([cent.centroid_id.ge(1000000),cent.centroid_id.between(100005,100411)],["S","G"],default="C")
cent["county_fips"]=np.where(cent.kind.eq("C"),cent.centroid_id,np.where(cent.kind.eq("S"),cent.centroid_id//1000,np.nan))
official=pd.read_parquet(R/"stage2_scripts/connector_test2_conus/official_roads.pq")
official["e_id"]=official.link_id.astype(str)
road=road.merge(official[["e_id","official","CTFIPS"]],on="e_id",how="left",validate="one_to_one")
oc=pd.read_parquet(R/"stage2_scripts/connector_test2_conus/official_connectors.pq")
oc["e_id"]=oc.link_id.astype(str)
conn=conn.merge(oc[["e_id","official"]],on="e_id",how="left",validate="one_to_one")
directional=pd.read_csv(R/"stage2_scripts/connector_test2_conus/directional_centroid_totals.csv")
cent=cent.merge(directional,on="centroid_id",how="left",validate="one_to_one")
def geometry_paths(frame,layer):
    if frame.empty:return
    count=len(frame); missing=0; out=[]
    for row in frame.to_dict("records"):
        path=list(row.pop("path"))
        segments=[]
        for eid in path:
            shape=geom.get(str(eid))
            if shape is None:
                missing+=1; continue
            if shape.geom_type=="LineString":segments.append(list(shape.coords))
            elif shape.geom_type=="MultiLineString":segments.extend([list(x.coords) for x in shape.geoms])
            else:raise ValueError(shape.geom_type)
        if not segments:raise ValueError("empty route geometry")
        row["origin_centroid_id"]=node_cid.get(str(row["origin_node"]))
        row["destination_centroid_id"]=node_cid.get(str(row["destination_node"]))
        row["edge_count"]=len(path)
        row["edge_ids_json"]=json.dumps(path,separators=(",",":"))
        row["geometry"]=MultiLineString(segments)
        out.append(row)
    assert missing==0,(layer,missing)
    write(gpd.GeoDataFrame(out,geometry="geometry",crs=crs),layer)
    sample_stats.append({"layer":layer,"sample_paths":count,"missing_geometry_edges":missing})
def sample_paths(name):
    # Deterministic highest-flow paths, plus the highest-flow path at every loaded G endpoint.
    # The window query reads endpoint/flow columns only; geometry/path is retrieved after IDs chosen.
    gs=",".join("'"+n+"'" for n in sorted(g_nodes))
    return sql("""
    WITH chosen AS (
      (SELECT od_id FROM """+name+""" WHERE flow>0 ORDER BY flow DESC,od_id LIMIT 250)
      UNION
      SELECT od_id FROM (SELECT od_id,row_number() OVER(PARTITION BY origin_node ORDER BY flow DESC,od_id) rn
        FROM """+name+""" WHERE flow>0 AND origin_node IN ("""+gs+""")) WHERE rn=1
      UNION
      SELECT od_id FROM (SELECT od_id,row_number() OVER(PARTITION BY destination_node ORDER BY flow DESC,od_id) rn
        FROM """+name+""" WHERE flow>0 AND destination_node IN ("""+gs+""")) WHERE rn=1)
    SELECT p.* FROM """+name+""" p SEMI JOIN chosen USING(od_id) WHERE p.flow>0 ORDER BY flow DESC,od_id
    """)
for scope,prefix in [("conus","n"),("harvey15","h")]:
    pre=json.loads((OPS/scope/"preflight.json").read_text())
    (OUT/(scope+"_preflight.json")).write_text(json.dumps(pre,indent=2))
    cv=pd.read_csv(OPS/scope/"conservation.csv")
    err=(cv.base-cv.moved-cv.retained).abs()
    checks.append({"scope":scope,"gate":"zone_pair_commodity_market_conservation","pass":bool((err<=1e-9*cv.base.abs()).all()),"value":float(err.max()),"limit":"1e-9 relative to each base cell"})
    ratio=pre["pilot_haul_mi"]/pre["baseline_haul_mi"]
    checks.append({"scope":scope,"gate":"geodesic_weighted_mean_haul","pass":.98<=ratio<=1.02,"value":ratio-1,"limit":"[-0.02,+0.02] relative to C+S"})
    pd.read_csv(OPS/scope/"gateway_budgets.csv").to_csv(OUT/(scope+"_gateway_budgets.csv"),index=False)
    cov=pd.read_csv(OPS/scope/"gateway_coverage.csv")
    cov.to_csv(OUT/(scope+"_gateway_coverage.csv"),index=False)
    for c in ["flow_status","in_scope","import","export"]:
        cent=cent.merge(cov[["centroid_id",c]].rename(columns={c:prefix+"_"+c}),on="centroid_id",how="left",validate="one_to_one")
    for arm,tag in [("control","c"),("gateway","g")]:
        variant=scope+"_connector_test2g_"+arm
        base=R/"results"/variant
        run=R/"results/rerouting_analysis"/variant/"304/1"
        f=pd.read_parquet(base/"edge_flows.gpq",columns=["e_id","acc_flow","current_capacity"])
        f.e_id=f.e_id.astype(str); f=f.set_index("e_id")
        for frame in [road,conn]:
            frame[prefix+"_"+tag+"_flow"]=frame.e_id.map(f.acc_flow)
        physical=f.loc[road.e_id]
        np.testing.assert_allclose(physical.current_capacity.to_numpy(),road.current_capacity.to_numpy(),rtol=0,atol=0)
        overshoot=float((physical.acc_flow-physical.current_capacity).max())
        checks.append({"scope":scope,"arm":arm,"gate":"physical_capacity_equal_and_not_exceeded","pass":overshoot<=1e-6,"value":overshoot,"limit":"identical physical capacity; flow <= capacity+1e-6"})
        view("p",base/"odpfc_parts/*.pq")
        totals=sql("SELECT count(*) paths,sum(flow) trips_day FROM p").iloc[0].to_dict()
        endpoints=sql("""SELECT node,sum(outflow) outflow,sum(inflow) inflow FROM (
          SELECT origin_node node,sum(flow) outflow,0.0 inflow FROM p GROUP BY origin_node
          UNION ALL SELECT destination_node node,0.0,sum(flow) FROM p GROUP BY destination_node) GROUP BY node""").set_index("node")
        cent[prefix+"_"+tag+"_out"]=cent.centroid_node.map(endpoints.outflow).fillna(0)
        cent[prefix+"_"+tag+"_in"]=cent.centroid_node.map(endpoints.inflow).fillna(0)
        checks.append({"scope":scope,"arm":arm,"gate":"baseline_full_delivery","pass":bool(np.isclose(totals["trips_day"],pre["trips_day"],rtol=1e-9,atol=0)),"value":totals["trips_day"],"limit":pre["trips_day"]})
        baseline_stats.append({"scope":scope,"arm":arm,**totals,"weighted_haul_mi":pre["baseline_haul_mi"] if arm=="control" else pre["pilot_haul_mi"]})
        samp=sample_paths("p")
        samp["scope"]=scope;samp["arm"]=arm;samp["state"]="intact_baseline"
        geometry_paths(samp,prefix+"_"+tag+"_baseline_paths")
        # Compare road flows only on shared IDs, preserving missing official records.
        score=road[["e_id","official","CTFIPS","faf5_class"]].copy()
        score["modeled"]=score.e_id.map(f.acc_flow)
        for label,mask in [("all_shared",pd.Series(True,index=score.index)),("Los_Angeles",pd.to_numeric(score.CTFIPS,errors="coerce").eq(6037)),("Harris",pd.to_numeric(score.CTFIPS,errors="coerce").eq(48201))]:
            a=score[mask & score.official.notna() & score.modeled.notna()]
            metrics.append({"scope":scope,"arm":arm,"area":label,"links":len(a),"missing_official":int(score.loc[mask,"official"].isna().sum()),"pearson":a.modeled.corr(a.official),"wape":(a.modeled-a.official).abs().sum()/a.official.sum(),"modeled_link_traversals_day":a.modeled.sum(),"official_link_traversals_day":a.official.sum()})
        costs=pd.read_csv(run/"cost_matrix_freight_by_scenario.csv")
        costs.insert(0,"arm",arm);costs.insert(0,"scope",scope);recover.append(costs)
        auditdir=OPS/variant
        for auditfile in ["baseline_shortcuts.log","recovery_shortcuts.log","verification_retry.log"]:
            p=auditdir/auditfile
            if p.exists():
                shutil.copy2(p,OUT/(variant+"_"+auditfile))
                if "shortcuts" in auditfile:
                    vals=[int(x) for x in re.findall(r"shortcuts=(\d+)",p.read_text())]
                    checks.append({"scope":scope,"arm":arm,"gate":auditfile,"pass":bool(vals) and max(vals)==0 and (len(vals)==12 if auditfile.startswith("recovery") else True),"value":max(vals) if vals else None,"limit":"0 shortcuts; recovery 12 path sets"})
        access=auditdir/"access_roads.csv"
        if access.exists():
            a=pd.read_csv(access);a.to_csv(OUT/(scope+"_gateway_access_roads.csv"),index=False)
            maxvc=float(a.vc_pilot.max())
            checks.append({"scope":scope,"gate":"freight_only_access_capacity","pass":maxvc<=1+1e-9,"value":maxvc,"limit":"V/C<=1; combined traffic not tested"})
        for day in [0,7,14,30,60,90]:
            view("post",run/("odpfc_freight_s1_day"+str(day)+".pq"))
            view("pre",run/("odpfc_freight_s1_day"+str(day)+"_baseline.pq"))
            # Exact path sequence and flow overlap, computed from every positive path.
            delta=sql("""WITH b AS (SELECT origin_node,destination_node,path,sum(flow) f FROM pre WHERE flow>0 GROUP BY ALL),
              p AS (SELECT origin_node,destination_node,path,sum(flow) f FROM post WHERE flow>0 GROUP BY ALL)
              SELECT (SELECT sum(flow) FROM pre) base_flow,(SELECT sum(flow) FROM post) post_flow,
              (SELECT count(*) FROM pre) base_paths,(SELECT count(*) FROM post) post_paths,
              sum(least(coalesce(b.f,0),coalesce(p.f,0))) unchanged_path_flow
              FROM b FULL JOIN p USING(origin_node,destination_node,path)""").iloc[0].to_dict()
            delta.update(scope=scope,arm=arm,day=day)
            delta["post_flow_on_changed_paths"]=delta["post_flow"]-delta["unchanged_path_flow"]
            changes.append(delta)
            if day in [0,7,90]:
                samp=sample_paths("pre")
                # Retrieve all realised paths for selected OD pairs on both intact and damaged network.
                chosen=samp[["origin_node","destination_node"]].drop_duplicates()
                db.register("chosen_pairs",chosen)
                for name,state in [("pre","intact_same_cohort"),("post","harvey_recovery")]:
                    s=sql("SELECT p.* FROM "+name+" p SEMI JOIN chosen_pairs USING(origin_node,destination_node) WHERE flow>0")
                    s["scope"]=scope;s["arm"]=arm;s["day"]=day;s["state"]=state
                    geometry_paths(s,prefix+"_"+tag+"_d"+str(day)+"_"+name+"_paths")
                # All-path cohort link volumes, not total-network flow.
                bv=sql("SELECT e_id,sum(flow) base_cohort_flow FROM (SELECT unnest(path) e_id,flow FROM pre) GROUP BY e_id")
                pv=sql("SELECT e_id,sum(flow) post_cohort_flow FROM (SELECT unnest(path) e_id,flow FROM post) GROUP BY e_id")
                m=bv.merge(pv,on="e_id",how="outer").fillna(0)
                m["delta_cohort_flow"]=m.post_cohort_flow-m.base_cohort_flow
                m["arm"]=arm;m["day"]=day;m["scope"]=scope
                gg=gpd.GeoDataFrame(m.merge(edges[["e_id","geometry","faf5_class"]],on="e_id",how="left",validate="one_to_one"),geometry="geometry",crs=crs)
                write(gg,prefix+"_"+tag+"_d"+str(day)+"_cohort_edges")
            iso=run/("trip_isolations_freight_s1_day"+str(day)+".pq")
            view("isolated",iso)
            isoends=sql("""SELECT node,sum(flow) endpoint_isolated_flow FROM (
                SELECT origin_node node,flow FROM isolated UNION ALL SELECT destination_node node,flow FROM isolated) GROUP BY node""")
            isoends["centroid_id"]=isoends.node.map(node_cid)
            isoends["kind"]=np.select([isoends.centroid_id.ge(1000000),isoends.centroid_id.between(100005,100411)],["S","G"],default="C")
            isoends["county_fips"]=np.where(isoends.kind.eq("C"),isoends.centroid_id,np.where(isoends.kind.eq("S"),isoends.centroid_id//1000,np.nan))
            isoends.to_csv(OUT/(variant+"_day"+str(day)+"_isolated_endpoints.csv"),index=False)
            if day==0:
                z=cent[["centroid_id","geometry"]].merge(isoends,on="centroid_id",how="inner")
                z["arm"]=arm;z["scope"]=scope
                write(gpd.GeoDataFrame(z,geometry="geometry",crs=crs),prefix+"_"+tag+"_d0_isolation")
        damage=pd.read_csv(R/"results/damage_analysis"/variant/"304/intersections_1_with_damage_values.csv",dtype={"e_id":str})
        damage.to_parquet(OUT/(variant+"_damage_rows.pq"),index=False)
        if scope=="conus" and arm=="gateway":
            asset=damage.road_label.astype(str).str.lower().isin(["bridge","tunnel"])
            cost=pd.concat([damage.loc[~asset].groupby("e_id").direct_damage_mean_usd.sum(),
                            damage.loc[asset].groupby("e_id").direct_damage_mean_usd.max()]).groupby(level=0).sum()
            agg=damage.groupby("e_id",as_index=False).agg(max_surface_depth_m=("flood_depth_surface","max"),max_river_depth_m=("flood_depth_river","max"),damaged_length_geodesic_m=("length_geodesic_m","sum"))
            agg["damage_usd"]=agg.e_id.map(cost)
            gg=edges[["e_id","geometry","faf5_class","road_classification","road_bridge"]].merge(agg,on="e_id",how="inner",validate="one_to_one")
            write(gg,"harvey_flood_damage_links")
            labelled=agg.merge(damage[["e_id","road_label"]].drop_duplicates(),on="e_id",validate="one_to_one")
            labelled.groupby("road_label",dropna=False).agg(damage_usd=("damage_usd","sum"),geodesic_m=("damaged_length_geodesic_m","sum"),links=("e_id","size")).to_csv(OUT/"damage_by_asset.csv")
            bins=pd.cut(labelled[["max_surface_depth_m","max_river_depth_m"]].max(axis=1),[-np.inf,0,.1,.3,.5,1,2,np.inf],right=True)
            labelled.groupby(bins,observed=False).agg(links=("e_id","size"),geodesic_m=("damaged_length_geodesic_m","sum"),damage_usd=("damage_usd","sum")).to_csv(OUT/"depth_distribution.csv")
    print("finished scope",scope,flush=True)
for prefix in ["n","h"]:
    for frame in [road,conn]:
        frame[prefix+"_delta_flow"]=frame[prefix+"_g_flow"]-frame[prefix+"_c_flow"]
for frame in [road,conn]:
    frame["official_flow_status"]=np.where(frame.official.isna(),"missing_record",np.where(frame.official.eq(0),"zero","positive"))
# Native CTFIPS is county of the physical link, not the centroid demand allocation.
write(road.drop(columns=["acc_flow"]),"roads_baseline_comparison")
write(conn.drop(columns=["acc_flow"]),"connectors_baseline_comparison")
write(cent,"centroid_loading_comparison")
pd.DataFrame(baseline_stats).to_csv(OUT/"baseline_summary.csv",index=False)
pd.DataFrame(metrics).to_csv(OUT/"official_road_agreement.csv",index=False)
pd.concat(recover).to_csv(OUT/"recovery_summary.csv",index=False)
pd.DataFrame(changes).to_csv(OUT/"all_path_change_statistics.csv",index=False)
pd.DataFrame(checks).to_csv(OUT/"decision_checks.csv",index=False)
pd.DataFrame(sample_stats).to_csv(OUT/"path_sample_manifest.csv",index=False)
pd.DataFrame(manifest).to_csv(OUT/"gis_layers.csv",index=False)
# Independent read-back validation of all exported layers.
import pyogrio
for row in manifest:
    info=pyogrio.read_info(GPKG,layer=row["layer"])
    assert info["features"]==row["features"],row
with sqlite3.connect(GPKG) as c:
    assert c.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
manifest_json={"source_root":str(R),"created":"2026-11-17","scope":"freight-only; C+S mean-parent control versus C+S+G","scenario":304,"recovery_scenario":1,"layers":manifest,"gis_integrity":"passed","checks_all_pass":bool(pd.DataFrame(checks)["pass"].all())}
(OUT/"manifest.json").write_text(json.dumps(manifest_json,indent=2))
shutil.rmtree(OUT/"ducktmp",ignore_errors=True)
print("DONE",json.dumps(manifest_json),flush=True)
