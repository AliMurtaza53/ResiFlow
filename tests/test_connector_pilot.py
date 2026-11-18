import geopandas as gpd
import pandas as pd
from shapely.geometry import Point,LineString,box
from resiflow.networks.connector_pilot import AccessIndex

def fixture():
    xy={0:(0,0),1:(500,0),2:(500,500),3:(0,500),4:(1000,0),5:(500,-500)}
    pairs=[(0,1),(1,2),(2,3),(3,0),(1,4),(1,5)]
    roads=gpd.GeoDataFrame({"e_id":[str(i) for i in range(6)],"from_id":[a for a,b in pairs],"to_id":[b for a,b in pairs],
        "assignment_tier":"arterial","road_classification":"primary","bridge_fraction":[0,0,0,0,0,1],"tunnel_fraction":0,
        "road_bridge":["no"]*5+["yes"],"current_capacity":1000},
        geometry=[LineString([xy[a],xy[b]]) for a,b in pairs],crs=9311)
    nodes=gpd.GeoDataFrame({"node_id":list(xy)},geometry=[Point(v) for v in xy.values()],crs=9311)
    return roads,nodes

def test_nested_exits_are_deterministic_and_do_not_bypass_cut_edges():
    r,n=fixture();idx=AccessIndex(r,n);before=r.copy()
    allcounts=[]
    for k in [2,3,4]:
        selected,audit=idx.select(["0"],box(-1000,-1000,2000,2000),total=k)
        allcounts.append([x["road_node"] for x in selected])
        assert {x["road_node"]:x["reason"] for x in audit}["4"]=="would_bypass_static_cut_edge"
        assert "5" not in [x["road_node"] for x in selected]
        assert len(selected)==k-1
    assert allcounts[0]==allcounts[2][:1]
    assert allcounts[1]==allcounts[2][:2]
    pd.testing.assert_frame_equal(r,before)

def test_facility_evidence_is_required_and_county_boundary_is_binding():
    r,n=fixture();idx=AccessIndex(r,n)
    assert idx.select(["0"],box(-1000,-1000,2000,2000),facility_points=[])[0]==[]
    selected,_=idx.select(["0"],box(-1000,-1000,2000,2000),facility_points=[Point(500,500)])
    assert [x["road_node"] for x in selected]==["2"]
    assert idx.select(["0"],box(-10,-10,10,10))[0]==[]

def test_original_stub_cannot_acquire_fictitious_redundancy():
    r,n=fixture();idx=AccessIndex(r,n)
    selected,audit=idx.select(["4"],box(-1000,-1000,2000,2000))
    assert selected==[]
    assert idx.main

def test_access_geometry_charges_the_native_and_local_distance_proxy():
    r,n=fixture();idx=AccessIndex(r,n)
    geometry=idx.access_geometry(LineString([(-10,0),(0,0)]),"0","2")
    assert geometry.length==1010.
    assert geometry.geom_type=="MultiLineString"


def test_label_only_and_numeric_structure_flags_cannot_be_access_routes():
    r,n=fixture()
    r['bridge_fraction']=0.;r['tunnel_fraction']=0.
    r['road_bridge']='no';r['road_tunnel']=0.
    r['road_label']=['road',' Bridge ','road','road','road','road']
    r.loc[2,'road_tunnel']=1.0
    idx=AccessIndex(r,n)
    assert idx.sensitive.iloc[1] and idx.sensitive.iloc[2]
    assert not {1,2}&set(idx.local.es['row'])
    selected,_=idx.select(['0'],box(-1000,-1000,2000,2000))
    assert '2' not in [row['road_node'] for row in selected]
