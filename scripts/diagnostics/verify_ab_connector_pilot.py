"""Mechanical gates for the fixed-OD A/B pilot (never selects a preferred outcome)."""
import argparse,json,re
from pathlib import Path
import numpy as np,pandas as pd
from resiflow.networks.hazard_eligibility import centroid_connector_mask,assert_centroid_flood_state,assert_physical_exposure

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--root",type=Path,required=True);p.add_argument("--inputs",type=Path,required=True)
    p.add_argument("--variant",required=True);p.add_argument("--case",choices=["freight","combined"],required=True)
    p.add_argument("--stage",choices=["baseline","hazard","damage","completion"],required=True)
    p.add_argument("--log",type=Path)
    a=p.parse_args();r=a.root/"results";out=a.inputs.parent/a.variant;out.mkdir(exist_ok=True)
    ref=pd.read_parquet(r/"conus_connector_test2g_gateway/edge_flows.gpq",columns=["e_id","faf5_class","current_capacity"])
    if a.stage=="completion":
        assert a.log is not None
        text=a.log.read_text(errors="replace")
        assert not re.search(r"INVARIANT[^\n]*ok=False",text)
        calls=[];last=None;initial=None
        for line in text.splitlines():
            if "The initial supply is " in line:
                initial=float(line.split("The initial supply is ",1)[1].strip())
            if "ITER_AUDIT iteration=" in line:
                last={k:float(v) for k,v in re.findall(r"([a-z_]+)=([-+0-9.eE]+)",line.split("ITER_AUDIT",1)[1])}
            if "The flow simulation is completed" in line and last:
                total=last.get("delivered_cum",0)+last.get("isolated_structural_cum",0)+last.get("isolated_congestion_cum",0)+last.get("remain",0)
                assert initial is not None
                np.testing.assert_allclose(total,initial,rtol=1e-9,atol=1e-6)
                assert last["remain"]<=max(total,1)*1e-9,"Unresolved recovery demand at the iteration cap"
                last['initial_supply']=initial
                calls.append(last);last=None;initial=None
        assert len(calls)==12,f"Expected six recovery plus six paired intact solves; found {len(calls)}"
        report={"completed_solves":len(calls),"maximum_solver_residual_flow":max(x['remain'] for x in calls),"solver_audits":calls}
    elif a.stage=="damage":
        old=pd.read_csv(r/"damage_analysis/conus_connector_test2g_gateway/damage_summary.csv")
        new=pd.read_csv(r/"damage_analysis"/a.variant/"damage_summary.csv")
        np.testing.assert_allclose(new.damage_cost_mean_usd,old.damage_cost_mean_usd,rtol=1e-9,atol=1e-6)
        report={"physical_damage_unchanged":True,"damage_usd":new.damage_cost_mean_usd.tolist()}
    elif a.stage=="hazard":
        folder=r/"disruption_analysis"/a.variant/"304"
        new=pd.read_parquet(folder/"links/road_links_1.gpq")
        old=pd.read_parquet(r/"disruption_analysis/conus_connector_test2g_gateway_virtual_exempt/304/links/road_links_1.gpq")
        assert_centroid_flood_state(new)
        exp=pd.read_parquet(folder/"intersections/intersections_1.pq",columns=["e_id"])
        assert_physical_exposure(new,exp)
        left=old[~centroid_connector_mask(old)].set_index("e_id").sort_index()
        right=new[~centroid_connector_mask(new)].set_index("e_id").sort_index()
        assert left.index.equals(right.index)
        for col in ["flood_depth_max","free_flow_speeds","current_capacity","max_speed","max_speed_truck"]:
            np.testing.assert_allclose(left[col],right[col],rtol=0,atol=0,equal_nan=True)
        assert left.damage_level_max.equals(right.damage_level_max)
        report={"physical_hazard_unchanged":True,"virtual_exposure":0,"unrestricted_virtual_links":int(centroid_connector_mask(new).sum())}
    else:
        new=pd.read_parquet(r/a.variant/"edge_flows.gpq",columns=["e_id","faf5_class","current_capacity"])
        left=ref[~centroid_connector_mask(ref)].set_index("e_id").sort_index()
        right=new[~centroid_connector_mask(new)].set_index("e_id").sort_index()
        assert left.index.equals(right.index)
        np.testing.assert_allclose(left.current_capacity,right.current_capacity,rtol=0,atol=0,equal_nan=True)
        audit=pd.read_parquet(a.root/"audit_dumps"/(a.variant+"_baseline")/"iteration_summary.parquet")
        last=audit.iloc[-1];first=audit.iloc[0]
        preflight=json.loads((a.inputs/"preflight.json").read_text())
        expected=preflight["freight_assignment_trips" if a.case=="freight" else "combined_assignment_pce"]
        np.testing.assert_allclose(first.requested_flow,expected,rtol=1e-9,atol=1e-5)
        assert last.remain<=expected*1e-9,"Unresolved baseline demand; do not call the pilot converged"
        np.testing.assert_allclose(last.delivered_cum+last.isolated_structural_cum+last.isolated_congestion_cum+last.remain,expected,rtol=1e-9,atol=1e-5)
        report={"physical_capacities_unchanged":True,"iterations":len(audit),"delivered":float(last.delivered_cum),
                "structural_isolation":float(last.isolated_structural_cum),"congestion_isolation":float(last.isolated_congestion_cum),
                "remain":float(last.remain),"requested":expected,"units":"trucks/day" if a.case=="freight" else "PCE/day"}
    report.update(variant=a.variant,case=a.case,stage=a.stage)
    (out/(a.stage+"_verified.json")).write_text(json.dumps(report,indent=2))
    print(json.dumps(report),flush=True)
if __name__=="__main__":main()
