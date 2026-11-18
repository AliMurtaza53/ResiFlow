"""Add physical routed mileage and verify final package references."""
from pathlib import Path
import sqlite3,json,hashlib,sys,re
import pandas as pd
P=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else Path(__file__).resolve().parent
with sqlite3.connect(P/"CSG_review.gpkg") as db:
    roads=pd.read_sql_query("SELECT length_mile,official,n_c_flow,n_g_flow,h_c_flow,h_g_flow FROM roads_baseline_comparison",db)
    connectors=pd.read_sql_query("SELECT length_mile,n_c_flow,n_g_flow,h_c_flow,h_g_flow FROM connectors_baseline_comparison",db)
b=pd.read_csv(P/"baseline_summary.csv")
rows=[]
for scope,pre in [("conus","n"),("harvey15","h")]:
    for arm,tag in [("control","c"),("gateway","g")]:
        flow=pre+"_"+tag+"_flow"
        trips=float(b[(b.scope==scope)&(b.arm==arm)].trips_day.iloc[0])
        vmt=float((roads.length_mile*roads[flow]).sum())
        shared=roads[roads.official.notna()]
        official_vmt=float((shared.length_mile*shared.official).sum())
        modeled_shared_vmt=float((shared.length_mile*shared[flow]).sum())
        rows.append({"scope":scope,"arm":arm,"trips_day":trips,"physical_routed_miles_day":vmt,"physical_route_miles_per_trip":vmt/trips,"synthetic_connector_miles_day":float((connectors.length_mile*connectors[flow]).sum()),"matched_road_modeled_vmt_day":modeled_shared_vmt,"matched_road_official_vmt_day":official_vmt,"matched_vmt_ratio":modeled_shared_vmt/official_vmt})
routed=pd.DataFrame(rows);routed.to_csv(P/"physical_routed_mileage.csv",index=False)
htmlfile=P/"DECISION_REPORT.html";text=htmlfile.read_text(encoding="utf-8")
section="""<h2>Physical routed mileage versus straight-line haul</h2><p>The ±2% allocation gate uses flow-weighted ellipsoidal straight-line OD endpoint distance; it is not a routed-mileage gate. The following table sums assigned physical link trips times the saved link length_mile and divides by unique input trips for mean physical route miles. Synthetic connector mileage is reported separately and is not physical truck VMT. Matched-road VMT uses the identical links with published records; it does not recover official trip-generation totals. Harvey-15 remains a subset-demand comparison.</p>"""+routed.to_html(index=False,border=0,float_format=lambda x:f"{x:,.6g}")
if "<h2>Physical routed mileage versus straight-line haul</h2>" in text:
    text=re.sub(r"<h2>Physical routed mileage versus straight-line haul</h2>.*?(?=<h2>)",section,text,flags=re.S)
else:
    text=text.replace("<h2>Baseline demand and haul</h2>",section+"<h2>Baseline demand and straight-line geodesic haul</h2>",1)
heading=re.search(r"<h1>.*?</h1>",text,flags=re.S)
assert heading
text=text[:heading.start()]+text[heading.end():]
text=text.replace("<body>","<body>"+heading.group(),1)
htmlfile.write_text(text,encoding="utf-8")
readme=P/"README.md"
clarification="Haul clarification: the ±2% allocation gate is straight-line geodesic OD distance. physical_routed_mileage.csv separately reports actual assigned physical-road miles from link flows and saved link lengths, excluding synthetic connector mileage."
if clarification not in readme.read_text(encoding="utf-8"):
    readme.write_text(readme.read_text(encoding="utf-8")+"\n"+clarification+"\n",encoding="utf-8")
manifest=json.loads((P/"manifest.json").read_text())
assert manifest["sealing_status"]=="HOLD_hazard_virtual_connector_policy"
assert len(manifest["layers"])==58
assert not manifest["checks_all_pass"] and manifest["baseline_mechanics_pass"]
assert int(pd.read_csv(P/"path_sample_manifest.csv").sample_paths.sum())==12090
prov=json.loads((P/"provenance.json").read_text())
for script in ["export_csg_gis_review.py","finalize_review.py","augment_virtual_findings.py","final_review_checks.py"]:
    prov[script+"_sha256"]=hashlib.sha256((P/script).read_bytes()).hexdigest()
prov["augmentation_sha256"]=prov["augment_virtual_findings.py_sha256"]
prov["final_report_sha256"]=hashlib.sha256(htmlfile.read_bytes()).hexdigest()
(P/"provenance.json").write_text(json.dumps(prov,indent=2))
print(routed.to_string(index=False));print("Final references and hold status verified.")
