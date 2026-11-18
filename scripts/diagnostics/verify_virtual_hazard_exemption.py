"""Fail a recovery chain if the virtual-link exemption changes physical hazard state."""
from pathlib import Path
import argparse, json
import numpy as np
import pandas as pd
from resiflow.networks.hazard_eligibility import centroid_connector_mask, assert_physical_exposure, assert_centroid_flood_state

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("old",type=Path);p.add_argument("new",type=Path)
    p.add_argument("--results-root",type=Path,required=True)
    p.add_argument("--damage",action="store_true")
    a=p.parse_args();root=a.results_root
    if a.damage:
        old=pd.read_csv(root/"damage_analysis"/a.old/"damage_summary.csv")
        new=pd.read_csv(root/"damage_analysis"/a.new/"damage_summary.csv")
        x=old.merge(new,on="event_id",validate="one_to_one",suffixes=("_old","_new"))
        assert len(x)==len(old)==len(new)
        np.testing.assert_allclose(x.damage_cost_mean_usd_old,x.damage_cost_mean_usd_new,rtol=1e-9,atol=1e-6)
        print(json.dumps({"physical_damage_unchanged":True,"new_damage_usd":x.damage_cost_mean_usd_new.tolist()}));return
    paths=[root/"disruption_analysis"/v/"304" for v in (a.old,a.new)]
    cols=["e_id","faf5_class","assignment_tier","flood_depth_max","damage_level_max","free_flow_speeds","current_capacity","max_speed","max_speed_truck"]
    old,new=[pd.read_parquet(v/"links/road_links_1.gpq",columns=cols) for v in paths]
    for f in (old,new):
        f.e_id=f.e_id.astype(str);assert f.e_id.is_unique
    assert set(old.e_id)==set(new.e_id)
    assert_centroid_flood_state(new)
    old_phys=old[~centroid_connector_mask(old)].set_index("e_id").sort_index()
    new_phys=new[~centroid_connector_mask(new)].set_index("e_id").sort_index()
    assert old_phys.index.equals(new_phys.index)
    for col in ["flood_depth_max","free_flow_speeds","current_capacity","max_speed","max_speed_truck"]:
        np.testing.assert_allclose(old_phys[col],new_phys[col],rtol=0,atol=0,equal_nan=True)
    assert old_phys.damage_level_max.equals(new_phys.damage_level_max)
    exposure=pd.read_parquet(paths[1]/"intersections/intersections_1.pq",columns=["e_id"])
    assert_physical_exposure(new,exposure)
    virtual=new[centroid_connector_mask(new)]
    print(json.dumps({"physical_links_unchanged":len(new_phys),"virtual_links_unrestricted":len(virtual),"virtual_exposure_records":0,"new":str(a.new)}))

if __name__=="__main__":main()
