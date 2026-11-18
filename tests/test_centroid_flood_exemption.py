"""Virtual flood geometry must not bypass or disable real physical access."""
import geopandas as gpd
import igraph
import pickle
import pandas as pd
import pytest
from shapely.geometry import LineString
from resiflow import road_revised as road
from resiflow.disruption import flood
from resiflow.disruption import intensity_hazard
from resiflow.disruption.build import (build_flood_link_disruption,
    build_earthquake_link_disruption,build_landslide_link_disruption,build_winter_storm_link_disruption)
from resiflow.fragility.flood_operational import apply_max_speed_to_links
from resiflow.hazards.base import HazardEvent
from resiflow.networks.hazard_eligibility import (
    centroid_connector_mask, assert_physical_exposure, assert_centroid_flood_state,
)


def test_classification_retains_unknown_physical_roads():
    f = pd.DataFrame({"faf5_class": pd.Series([50, pd.NA, 14, pd.NA], dtype="Int64"),
                      "assignment_tier": ["other", "arterial", "arterial", "centroid_connector"]})
    assert centroid_connector_mask(f).tolist() == [True, False, False, True]


def test_virtual_links_never_reach_raster_sampling(monkeypatch):
    f = gpd.GeoDataFrame({"e_id": ["c", "r", "unknown"], "faf5_class": [50, 14, None]},
        geometry=[LineString([(0, 0), (1, 1)])] * 3, crs=4326)
    seen = []
    def footprint(links, path):
        seen.extend(links.e_id)
        return links
    monkeypatch.setattr(flood, "subset_features_to_raster_extent", footprint)
    monkeypatch.setattr(flood, "clip_features", lambda links, *args: links.iloc[:0])
    assert flood.intersections_with_damage(f, "1", "surface", "unused", None) is None
    assert seen == ["r", "unknown"]
    seen.clear()
    assert flood.intersections_with_damage(f.iloc[:1], "1", "surface", "unused", None) is None
    assert seen == []


@pytest.mark.parametrize('field',['pga_g','landslide_mm','winter_storm_mm'])
def test_other_hazards_exclude_virtual_before_sampling(monkeypatch,field):
    links=gpd.GeoDataFrame({'e_id':['c','r','unknown'],'faf5_class':[50,14,None]},
        geometry=[LineString([(0,0),(1,1)])]*3,crs=4326)
    seen=[]
    def footprint(frame,path):seen.extend(frame.e_id);return frame
    monkeypatch.setattr(intensity_hazard,'subset_features_to_raster_extent',footprint)
    monkeypatch.setattr(intensity_hazard,'clip_features',lambda frame,*args:frame.iloc[:0])
    result=intensity_hazard.intersections_with_intensity(links,'1','unused',None,
        field_name=field,intensity_col=field,damage_level_col='level',categorical_fn=lambda *x:None)
    assert result is None and seen==['r','unknown']


def test_other_hazard_aggregation_rejects_legacy_virtual_records():
    links=gpd.GeoDataFrame({'e_id':['c'],'faf5_class':[50]},geometry=[LineString([(0,0),(1,1)])],crs=4326)
    exposure=pd.DataFrame({'e_id':['c'],'im':[1.],'level':['minor']})
    assert_physical_exposure(links,pd.DataFrame())
    with pytest.raises(ValueError,match='Rerun stage 2'):
        intensity_hazard.features_with_intensity(links,exposure,intensity_col='im',intensity_max_col='im_max',damage_level_col='level')


@pytest.mark.parametrize('hazard,field,damage,builder,unit',[
    ('earthquake','pga_g','damage_level_earthquake',build_earthquake_link_disruption,'g_pga'),
    ('landslide','landslide_mm','damage_level_landslide',build_landslide_link_disruption,'mm_displacement'),
    ('winter_storm','winter_storm_mm','damage_level_winter_storm',build_winter_storm_link_disruption,'mm_snow')])
def test_nonflood_builders_leave_virtual_open_and_physical_unchanged(hazard,field,damage,builder,unit):
    links=gpd.GeoDataFrame({'e_id':['c','r'],'faf5_class':[50,14],
        'road_classification':['centroid_connector','primary'],'road_label':['road','road'],'road_bridge':['no','no']},
        geometry=[LineString([(0,0),(1,0)]),LineString([(1,0),(2,0)])],crs=4326)
    baseline=pd.DataFrame({'e_id':['c','r'],'free_flow_speeds':[25.,40.],'current_capacity':[10000.,1000.]})
    exposure=pd.DataFrame({'e_id':['r'],field:[.8],damage:['minor']})
    event=HazardEvent(hazard,'1',unit)
    all_links=builder(links,exposure.copy(),baseline,hazard_event=event,scenario_param=1)
    physical=builder(links.iloc[1:],exposure.copy(),baseline.iloc[1:],hazard_event=event,scenario_param=1)
    pd.testing.assert_frame_equal(all_links[all_links.e_id.eq('r')].reset_index(drop=True),physical.reset_index(drop=True))
    assert_centroid_flood_state(all_links)
    assert not all_links.loc[all_links.e_id.eq('c'),'hazard_exposure_applicable'].iloc[0]


def test_stage2_preserves_physical_state_and_all_routing_links():
    links = gpd.GeoDataFrame({"e_id": ["c", "r"], "faf5_class": [50, 14],
        "from_id": ["900", "1"], "to_id": ["1", "2"]},
        geometry=[LineString([(0, 0), (1, 0)]), LineString([(1, 0), (2, 0)])], crs=4326)
    baseline = pd.DataFrame({"e_id": ["c", "r"], "free_flow_speeds": [25., 40.],
                             "current_capacity": [10000., 1000.]})
    exposure = pd.DataFrame({"e_id": ["r"], "flood_depth_surface": [.8], "damage_level_surface": ["minor"]})
    event = HazardEvent("flood", "1", "m_depth")
    all_links = build_flood_link_disruption(links, exposure.copy(), baseline, hazard_event=event, scenario_param=304, closure_threshold=30)
    physical = build_flood_link_disruption(links.iloc[1:], exposure.copy(), baseline.iloc[1:], hazard_event=event, scenario_param=304, closure_threshold=30)
    pd.testing.assert_frame_equal(all_links[all_links.e_id.eq("r")].reset_index(drop=True), physical.reset_index(drop=True))
    assert all_links.e_id.tolist() == ["c", "r"]
    pd.testing.assert_series_equal(all_links.current_capacity, baseline.current_capacity, check_names=False)
    c = all_links.iloc[0]
    assert c.max_speed == c.max_speed_truck == 25
    assert c.flood_depth_max == c.intensity_primary == 0
    assert c.damage_level_max == "no" and not c.hazard_exposure_applicable
    assert_centroid_flood_state(all_links)


def test_contaminated_exposure_and_legacy_recovery_state_fail():
    links = pd.DataFrame({"e_id": ["c", "r"], "faf5_class": [50, 14],
                          "flood_depth_max": [2.5, .8], "free_flow_speeds": [25., 40.],
                          "max_speed": [0., 0.], "damage_level_max": ["no", "minor"]})
    with pytest.raises(ValueError, match="Rerun stage 2"):
        assert_physical_exposure(links, pd.DataFrame({"e_id": ["c"]}))
    assert_physical_exposure(links, pd.DataFrame({"e_id": ["r"]}))
    with pytest.raises(ValueError, match="Rerun stages 2 and 3"):
        assert_centroid_flood_state(links)
    clean = apply_max_speed_to_links(links, depth_key=30, truck_depth_key=60)
    assert_centroid_flood_state(clean)
    clean.loc[0, "damage_level_max"] = "minor"
    with pytest.raises(ValueError):
        assert_centroid_flood_state(clean)


@pytest.mark.parametrize("exits,closed,reachable", [(1, False, True), (1, True, False), (2, True, True), (2, "both", False)])
def test_physical_access_closures_remain_effective(exits, closed, reachable, monkeypatch):
    # A nearby open B road is not usable unless the origin has a real second exit.
    # The endpoint-only suite separately tests third-centroid shortcuts.
    # Remove non-endpoint centroid 902 from THIS operational fixture so it
    # also tests the standalone exemption against integration's public worker
    # API, without importing the unmerged endpoint-routing implementation.
    pairs = [("900", "1"), ("3", "901"), ("1", "3"), ("2", "3"), ("902", "1"), ("902", "2")]
    classes = [50, 50, 14, 14, 50, 50]
    depths = [2.5, 2.5, .8 if closed else 0., .8 if closed == "both" else 0., 2.5, 2.5]
    if exits == 2:
        pairs.append(("900", "2")); classes.append(50); depths.append(2.5)
    f = pd.DataFrame({"e_id": [str(i) for i in range(len(pairs))], "faf5_class": classes,
                      "flood_depth_max": depths, "free_flow_speeds": 25., "current_capacity": 1000.})
    state = apply_max_speed_to_links(f, depth_key=30, truck_depth_key=60)
    pd.testing.assert_series_equal(state.current_capacity, f.current_capacity)
    valid = [i for i, s in enumerate(state.max_speed) if s > 0]
    graph = igraph.Graph.TupleList((pairs[i] for i in valid), directed=False)
    graph.delete_vertices([v.index for v in graph.vs if v["name"]=="902"])
    graph.vs["faf_centroid"] = [n in {"900", "901", "902"} for n in graph.vs["name"]]
    graph.es["weight"] = [1.] * graph.ecount()
    for attr, value in [("shared_network", None), ("_name_to_idx", {}), ("_arrival_by_departure", {}), ("_routing_arc_to_edge", [])]:
        monkeypatch.setattr(road, attr, value, raising=False)
    road.worker_init_path(pickle.dumps(graph))
    if reachable:
        paths = road.find_least_cost_path((900, [901], [10.]))[2]
        assert paths[0]
    else:
        with pytest.warns(RuntimeWarning):
            paths = road.find_least_cost_path((900, [901], [10.]))[2]
        assert paths == [[]]
