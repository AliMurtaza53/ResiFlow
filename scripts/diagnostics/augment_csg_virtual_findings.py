"""Add the extended virtual-connector flood audit to the GIS decision package."""
from pathlib import Path
import json, hashlib, sqlite3, copy, re, sys
import xml.etree.ElementTree as ET
import pandas as pd
import numpy as np
import geopandas as gpd
import pyogrio
P=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parent
F=P/"CSG_review.gpkg"
states=pd.read_csv(P/"synthetic_connector_flood_states.csv",dtype={"e_id":str})
conn=gpd.read_file(F,layer="connectors_baseline_comparison");conn.e_id=conn.e_id.astype(str)
states=states.drop(columns=["faf5_class"])
conn=conn.drop(columns=[c for c in states if c!="e_id"],errors="ignore").merge(states,on="e_id",validate="one_to_one")
conn.to_file(F,layer="connectors_baseline_comparison",driver="GPKG",index=False)
closed=conn[conn.max_speed.le(0)].copy()
closed["state_day"]=0
closed["closure_basis"]="raster exposure of virtual geometry; requires policy correction"
closed.to_file(F,layer="synthetic_connectors_closed_by_flood",driver="GPKG",index=False)
assert len(closed)==41 and closed.damage_level_max.eq("no").all()
cent=gpd.read_file(F,layer="centroid_loading_comparison")
closedn=closed.groupby("centroid_id").size()
alln=conn.groupby("centroid_id").size()
affected=cent[cent.centroid_id.isin(closed.centroid_id)].copy()
affected["closed_connectors"]=affected.centroid_id.map(closedn)
affected["total_connectors"]=affected.centroid_id.map(alln)
affected["all_connectors_closed"]=affected.closed_connectors.eq(affected.total_connectors)
affected.to_file(F,layer="centroids_affected_virtual_flood_closure",driver="GPKG",index=False)
affected.drop(columns="geometry").to_csv(P/"centroids_with_flood_closed_connectors.csv",index=False)
group=closed.groupby("kind",as_index=False).agg(closed_links=("e_id","size"),centroids=("centroid_id","nunique"),control_connector_traversals_day=("n_c_flow","sum"),gateway_connector_traversals_day=("n_g_flow","sum"))
group.to_csv(P/"synthetic_connector_closure_by_group.csv",index=False)
# All wet class-50 rows get their own category, never masquerading as unknown physical roads.
wet=pd.read_parquet(P/"flood_intersections_all.pq");wet.e_id=wet.e_id.astype(str)
with sqlite3.connect(F) as db:
    roads=pd.read_sql_query("SELECT e_id,hpms_fclass,road_label FROM roads_baseline_comparison",db)
wet=wet.merge(roads,on="e_id",how="left",validate="many_to_one")
virtual=wet.e_id.isin(set(conn.e_id))
wet["asset"]=wet.road_label.fillna("unknown")
wet.loc[virtual,"asset"]="virtual_connector"
wet["class_group"]=np.select([wet.hpms_fclass.isin([1,2,3]),wet.hpms_fclass.isin([4,5,6,7])],["F1-F3","F4-F7"],default="unknown_HPMS_class")
wet.loc[virtual,"class_group"]="virtual_connector"
wet["wet"]=wet.flood_depth_surface.gt(0)
floodstats=wet.groupby(["class_group","asset"],dropna=False).agg(pieces=("e_id","size"),wet_pieces=("wet","sum"),links=("e_id","nunique"),wet_geodesic_m=("length_geodesic_m",lambda s:s[wet.loc[s.index,"wet"]].sum())).reset_index()
w=wet[wet.wet].groupby(["class_group","asset"]).e_id.nunique()
floodstats["wet_links"]=[w.get((r.class_group,r.asset),0) for r in floodstats.itertuples()]
floodstats["wet_piece_share"]=floodstats.wet_pieces/floodstats.pieces
floodstats.to_csv(P/"flooded_links_by_class_and_asset.csv",index=False)
physical=wet[~virtual]
depth=physical.groupby("e_id").flood_depth_surface.max()
depthstats=depth.describe(percentiles=[.01,.5,.95,.99]).rename("physical_link_max_depth_m").reset_index()
depthstats.to_csv(P/"link_depth_summary.csv",index=False)
pd.cut(depth,[-np.inf,0,.1,.3,.5,1,2,9.144,np.inf]).value_counts(sort=False).rename_axis("physical_link_max_depth_m").rename("links").to_csv(P/"depth_distribution.csv")
ok=physical.length.ge(1)&physical.length_geodesic_m.notna()
ratio=physical.loc[ok,"length_geodesic_m"]/physical.loc[ok,"length"]
lc={"scope":"physical roads only; virtual connectors excluded","pieces_ge_1m":int(ok.sum()),"projected_total_m":float(physical.loc[ok,"length"].sum()),"geodesic_total_m":float(physical.loc[ok,"length_geodesic_m"].sum()),"total_ratio":float(physical.loc[ok,"length_geodesic_m"].sum()/physical.loc[ok,"length"].sum()),"ratio_p01":float(ratio.quantile(.01)),"ratio_p50":float(ratio.quantile(.5)),"ratio_p99":float(ratio.quantile(.99))}
(P/"length_check_physical_only.json").write_text(json.dumps(lc,indent=2))
damage=pd.read_csv(P/"damage_by_asset.csv")
if not damage.road_label.eq("tunnel").any():
    damage=pd.concat([damage,pd.DataFrame([{"road_label":"tunnel","damage_usd":0.0,"damaged_links":0,"damage_bearing_geodesic_m":0.0}])],ignore_index=True)
damage.to_csv(P/"damage_by_asset.csv",index=False)
checks=pd.read_csv(P/"decision_checks.csv")
baseline_pass=bool(checks.loc[~checks.gate.eq("extended_audit_virtual_connector_flood_exemption"),"pass"].all())
checks=pd.concat([checks,pd.DataFrame([{"scope":"both","arm":"both","gate":"extended_audit_virtual_connector_flood_exemption","pass":False,"value":len(closed),"limit":"0 synthetic access links speed-restricted by their drawn-line raster exposure; new verification finding"}])],ignore_index=True).drop_duplicates(["scope","arm","gate"],keep="last")
checks.to_csv(P/"decision_checks.csv",index=False)
sensitivity=pd.read_csv(P/"virtual_connector_reachability_sensitivity.csv")
layers=pd.read_csv(P/"gis_layers.csv")
extras=[{"layer":"synthetic_connectors_closed_by_flood","features":len(closed)},{"layer":"centroids_affected_virtual_flood_closure","features":len(affected)}]
layers=pd.concat([layers,pd.DataFrame(extras)],ignore_index=True).drop_duplicates("layer",keep="last")
layers.to_csv(P/"gis_layers.csv",index=False)
# Make new finding visible when the QGIS project opens.
tree=ET.parse(P/"CSG_review.qgs");root=tree.getroot()
projectlayers=root.find("projectlayers");lt=root.find("layer-tree-group")
newnames={"synthetic_connectors_closed_by_flood","centroids_affected_virtual_flood_closure"}
for entry in list(projectlayers):
    if entry.findtext("layername") in newnames:projectlayers.remove(entry)
for entry in list(lt):
    if entry.attrib.get("name") in newnames:lt.remove(entry)
for name,template in [("synthetic_connectors_closed_by_flood","connectors_baseline_comparison"),("centroids_affected_virtual_flood_closure","centroid_loading_comparison")]:
    src=next(e for e in projectlayers.findall("maplayer") if e.findtext("layername")==template)
    ml=copy.deepcopy(src)
    lid=name+"_audit"
    ml.find("id").text=lid;ml.find("layername").text=name;ml.find("datasource").text="./CSG_review.gpkg|layername="+name;ml.find("subsetstring").text=""
    for prop in ml.findall(".//prop"):
        if prop.attrib.get("k") in ["color","line_color"]:prop.set("v","188,35,35,255")
    projectlayers.insert(0,ml)
    lt.insert(0,ET.Element("layer-tree-layer",id=lid,name=name,source="./CSG_review.gpkg|layername="+name,providerKey="ogr",checked="Qt::Checked",expanded="0"))
tree.write(P/"CSG_review.qgs",encoding="utf-8",xml_declaration=True)
def table(x):return x.to_html(index=False,border=0,float_format=lambda v:f"{v:,.6g}")
title="HOLD the C+S+G Harvey seal: synthetic centroid connectors receive flood closures"
block="""<section><h2>Extended audit: a substantive reason to hold sealing</h2>
<p>The original allocation, conservation, haul, endpoint-only routing and freight baseline capacity checks pass. An additional review found 41 Class-50 centroid connectors closed by the raster depth on their synthetic geometry: 31 C, 3 S and 7 G links. All retain damage_level_max='no'. Of these, 40 also have zero truck-specific speed. Connector 633909 at Houston gateway 100146 is assigned 2.571 m depth and closed, despite representing abstract loading access rather than a physical road.</p>
<p>This is an operational-exposure policy problem, not a disconnected baseline endpoint and not repeated bridge damage. The immediate physical Houston approach road 633911 has zero depth and positive speed, but other physical closures can still isolate the facility. Therefore the connector's 9,286.82 baseline trips/day must not all be claimed recoverable.</p>
<p>The table below reopens virtual access arcs only, holds physical-road closures fixed, and tests endpoint-only reachability. Day 0 uses the initial physical graph; day 7 uses each arm's saved post-assignment speeds/capacities. These are topology sensitivities, not reassigned demand or revised recovery results. They quantify why the existing small G-versus-control isolation differences are provisional.</p>"""+table(sensitivity)+table(group)+"""
<p>Full CONUS: at day 0, 53.19 isolated trips/day in the G arm gain a physical path when only virtual connectors reopen (control: 74.74). At day 7 the corresponding snapshot values are 1,388.07 and 1,506.00. The difference in that day-7 sensitivity exceeds the reported 96.84-trip G-versus-control isolation benefit. This does not establish that the benefit will reverse: reachability is not a capacity-feasible assignment. It establishes that the comparison is not ready to seal. Some saved isolated day-7 demand already has a path in the post-assignment snapshot; a path alone does not prove sufficient capacity.</p>
<h3>Recommended next action</h3><ol>
<li>Freeze the audited freight OD inputs as a versioned experimental allocation. Hold the hazard/recovery seal.</li>
<li>Exempt Class 50 synthetic connectors from physical raster exposure, damage, and geometry-based speed/closure/recovery restrictions. Keep every actual road and bridge at their access ends subject to the hazard. Retain endpoint-only routing and shared physical capacity.</li>
<li>Add regressions: a wet virtual line with dry physical access stays available; a flooded physical approach still closes; no through-centroid shortcut appears.</li>
<li>Reuse the four finished freight baselines and rerun the matched CONUS and Harvey-15 stages 2–4 after that policy fix. Recheck isolation and rerouting before accepting the C+S+G Harvey result.</li>
<li>Then perform the combined passenger/freight loading-point capacity gate. Investigate Harris I-610 route/destination distribution separately; do not tune G shares solely to improve published-flow correlation.</li></ol>
<p>The public directional connector flows do not identify true facility OD pairs. This G variant reallocates import origins and export destinations; domestic freight facility allocation is not reconstructed. Eligible reconstructed import/export cells account for 8.06% of the full-CONUS input; 6.68% of all trips move to G. This is scoped evidence, not a complete independent facility demand model.</p>
<h3>Complete physical flood checks, corrected categorization</h3><p>The preceding source length_check_1.json includes all intersected model links, including virtual connectors. Physical-only length checks are supplied separately. The depth summary below excludes Class 50; the class table lists virtual connectors explicitly rather than labelling them unknown physical roads.</p>"""+table(depthstats)+table(floodstats)+"""</section>"""
report=P/"DECISION_REPORT.html";text=report.read_text(encoding="utf-8")
old="C+S+G mechanics pass; agreement is mixed; freeze the freight variant, hold combined acceptance"
text=text.replace(old,title)
text=text.replace("<body>","<body>"+block,1)
text=re.sub(r"<h2>Decision gates</h2>.*?(?=<h2>)","<h2>Decision checks including the extended audit</h2><p>Original tolerances: conservation 1e-9 relative, weighted mean haul ±2%, zero centroid shortcuts, complete baseline delivery and matched physical capacities. The additional virtual-connector closure audit is a verification finding, not a fit target.</p>"+table(checks),text,flags=re.S)
text=text.replace("<h2>Review maps and package contents</h2>","<h2>Path preview and original layers; extended audit layers described above</h2>")
# Remove now-obsolete all-link depth/class tables later in report; keep damage and source-length context.
import re
text=re.sub(r"<h2>Damage and complete flood checks</h2>.*?(?=<h2>)","<h2>Damage and physical flood checks</h2><p>Bridge/tunnel costs counted once per physical link; road pieces summed. See the extended audit above for physical-only depth/class statistics and length_check_physical_only.json. Direct physical damage is unchanged across arms.</p>"+table(damage),text,flags=re.S)
report.write_text(text,encoding="utf-8")
readme=P/"README.md"
lead="""# HOLD: virtual connectors are being closed by raster exposure
Start with synthetic_connectors_closed_by_flood and centroids_affected_virtual_flood_closure.
The baseline OD/loading mechanics pass, but 41 abstract connectors receive flood closure, including Houston 100146. Existing Harvey isolation comparisons are provisional. See the first section of DECISION_REPORT.html and virtual_connector_reachability_sensitivity.csv for the quantified effect and required next steps.
This package reports the existing runs; it does not implement or simulate the policy correction.
\n"""
readme.write_text(lead+readme.read_text(encoding="utf-8"),encoding="utf-8")
manifest=json.loads((P/"manifest.json").read_text())
manifest.update(layers=layers.to_dict("records"),baseline_mechanics_pass=baseline_pass,checks_all_pass=False,sealing_status="HOLD_hazard_virtual_connector_policy",extended_virtual_audit_jobs=[3791078,3791088])
with sqlite3.connect(F) as db:assert db.execute("PRAGMA integrity_check").fetchone()[0]=="ok"
for row in layers.to_dict("records"):assert pyogrio.read_info(F,layer=row["layer"])["features"]==int(row["features"])
(P/"manifest.json").write_text(json.dumps(manifest,indent=2))
provenance=json.loads((P/"provenance.json").read_text())
with F.open("rb") as fh:provenance["gis_sha256"]=hashlib.file_digest(fh,"sha256").hexdigest()
provenance["augmentation_sha256"]=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
provenance["extended_virtual_audit_jobs"]=[3791078,3791088]
provenance["ct_loading_export_job"]=3791056
(P/"provenance.json").write_text(json.dumps(provenance,indent=2))
print(title);print(sensitivity.to_string(index=False));print("GIS layers",len(layers))
