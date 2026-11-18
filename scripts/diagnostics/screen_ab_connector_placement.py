"""Predeclared nearest-access alternative: time-only diagnostic, never a tuning rule."""
from pathlib import Path
import argparse,json
import numpy as np,pandas as pd,geopandas as gpd,duckdb,igraph as ig
from resiflow.networks.connector_pilot import AccessIndex
from resiflow.networks.hazard_eligibility import centroid_connector_mask
from resiflow import road_revised as road

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--inputs',type=Path,required=True)
    a=p.parse_args();root=a.root;inp=a.inputs
    A=gpd.read_parquet(inp/'network_A.gpq')
    baseline=pd.read_parquet(root/'results/conus_connector_test2g_gateway/edge_flows.gpq',columns=['e_id','faf5_class','current_capacity','time_hr'])
    valid=set(baseline.loc[~centroid_connector_mask(baseline)&baseline.current_capacity.gt(.5),'e_id'].astype(str))
    physical=A[A.e_id.isin(valid)].copy()
    nodes=gpd.read_parquet(root/'soge_clusters/networks/faf5/faf5_road_nodes.gpq').to_crs(A.crs)
    index=AccessIndex(physical,nodes)
    audit=gpd.read_file(inp/'pilot_review.gpkg',layer='candidate_audit')
    coverage=pd.read_csv(inp/'unit_coverage.csv',dtype={'unit_node':str,'county_fips':str})
    new=[];choices=[]
    for unit in coverage.itertuples():
        own=A[centroid_connector_mask(A)&A.from_id.eq(unit.unit_node)]
        selected=list(set(own.to_id)&index.main)
        eligible=audit[audit.unit_node.astype(str).eq(unit.unit_node)&audit.reason.isin(['eligible','selected'])]
        # Fixed alternate rule: shortest screened local access first, then node ID.
        for row in eligible.sort_values(['access_path_m','road_node']).itertuples():
            n=str(row.road_node);point=index.points.loc[n].geometry
            if len(selected)>=4:break
            if n in selected or min(point.distance(index.points.loc[k].geometry) for k in selected)<150:continue
            base=own[own.to_id.eq(str(row.anchor))].iloc[0].copy()
            base['e_id']=f'pilot_alt_{unit.unit_node}_{len(selected)+1}';base['to_id']=n
            base['geometry']=index.access_geometry(base.geometry,str(row.anchor),n)
            base['length']=base.geometry.length;base['pilot_added_exit']=True
            base['AB_FinalSpeed']=base['BA_FinalSpeed']=base['Speed_Limit']=25.
            new.append(base);selected.append(n)
            choices.append(dict(unit_node=unit.unit_node,county_fips=unit.county_fips,road_node=n,access_path_m=row.access_path_m))
    assert new,'No alternate placement could be screened'
    alt=gpd.GeoDataFrame(new,geometry='geometry',crs=A.crs)
    alt.to_file(inp.parent/'pilot_alternate_review.gpkg',layer='nearest_access_alternatives',driver='GPKG')
    pd.DataFrame(choices).to_csv(inp.parent/'alternate_placement_choices.csv',index=False)
    frame=gpd.GeoDataFrame(pd.concat([A,alt],ignore_index=True),geometry='geometry',crs=A.crs)
    frame=frame[frame.e_id.isin(valid)|centroid_connector_mask(frame)].copy()
    times=frame.e_id.map(baseline.set_index('e_id').time_hr)
    missing=times.isna();times.loc[missing]=frame.loc[missing].geometry.length/1609.344/25.
    centers=set(frame.loc[centroid_connector_mask(frame),'from_id'])
    graph=ig.Graph.TupleList(frame[['from_id','to_id']].itertuples(index=False,name=None),directed=False)
    graph.es['weight']=times.tolist();graph.vs['faf_centroid']=[str(n) in centers for n in graph.vs['name']]
    road._set_worker_network(graph)
    units=','.join("'"+str(n)+"'" for n in coverage.unit_node if not str(n).startswith('1900'))
    freight=root/'stage2_scripts/connector_test2_gateway_full/conus/harvey15_gateway_od.pq'
    db=duckdb.connect();db.execute('SET threads=4')
    pairs=db.execute("SELECT origin_node,destination_node,Car21 FROM read_parquet(?) WHERE (CAST(origin_node AS VARCHAR) IN ("+units+") OR CAST(destination_node AS VARCHAR) IN ("+units+")) AND CAST(origin_node AS VARCHAR) <> CAST(destination_node AS VARCHAR) ORDER BY Car21 DESC,origin_node,destination_node LIMIT 250",[str(freight)]).df()
    total=0.;trips=0.
    for origin,rows in pairs.groupby('origin_node'):
        _,_,paths,flows=road.find_least_cost_path((int(origin),rows.destination_node.tolist(),rows.Car21.tolist()))
        for destination,path,flow in zip(rows.destination_node,paths,flows):
            assert path,'Unreachable alternate diagnostic pair'
            total+=float(times.iloc[path].sum())*flow;trips+=flow
            used=frame.iloc[path]
            assert not any(str(n) in centers and str(n) not in {str(origin),str(destination)} for n in used.loc[centroid_connector_mask(used),'from_id'])
    result={'variant':'B4_nearest_access_speed25','sample_pairs':len(pairs),'sample_trips':trips,
        'mean_path_time_hr':total/trips,'centroid_shortcuts':0,'scope':'time-only placement diagnostic; never capacity, isolation, or selection target'}
    (inp.parent/'alternate_placement_screen.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))

if __name__=='__main__':main()
