"""Export the stopped pilot's GIS, node list and offline maps. No assignment is run."""
from pathlib import Path
import argparse,base64,html,json,shutil
import numpy as np,pandas as pd,geopandas as gpd,igraph as ig
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from shapely import from_wkb
from shapely.geometry import box,MultiLineString

NAMES={'06037':'Los Angeles / Long Beach','48201':'Harris','53011':'Clark WA','48039':'Brazoria','48071':'Chambers'}
COLORS={'existing_exit':'#202020','selected':'#118562','eligible':'#849544',
    'no_eligible_public_road_attachment':'#c53c38','too_close_to_existing_exit':'#e8a13c',
    'would_bypass_static_cut_edge':'#8547ae','local_route_exceeds_3km_or_crosses_structure':'#317cbd',
    'outside_county':'#a5a5a5','no_same_facility_reference_within_300m':'#c96698'}

def main():
    p=argparse.ArgumentParser();p.add_argument('--folder',type=Path,required=True);p.add_argument('--reference',type=Path,required=True)
    p.add_argument('--refresh-maps',action='store_true',help='Keep the already-created GIS file; refresh owned maps and tables')
    a=p.parse_args();out=a.folder;source=out/'pilot_review.gpkg'
    units=pd.read_csv(out/'unit_coverage.csv',dtype={'unit_node':str,'county_fips':str})
    registry=pd.read_csv(out/'node_registry.csv',dtype={'node_id':str,'county_fips':str})
    A=pd.read_csv(out/'connectors_A.csv',dtype=str);B=pd.read_csv(out/'connectors_B4.csv',dtype=str)
    old=gpd.read_file(source,layer='existing_exits');new=gpd.read_file(source,layer='added_exits')
    roads=gpd.read_file(source,layer='physical_roads');points=gpd.read_file(source,layer='loading_units')
    audit=gpd.read_file(source,layer='candidate_audit')
    for frame in [old,new]:frame['from_id']=frame.from_id.astype(str)
    points['node_id']=points.node_id.astype(str);audit['unit_node']=audit.unit_node.astype(str)
    audit['county_fips']=audit.county_fips.astype(str).str.zfill(5)
    boundary=gpd.read_file(a.reference,layer='pilot_counties').to_crs(roads.crs)
    boundary['GEOID']=boundary.GEOID.astype(str).str.zfill(5)
    references=gpd.read_file(a.reference,layer='faf5_centroids_near_gateway_features')
    records=[]
    for row in units.itertuples():
        first=A[A.centroid_node.eq(row.unit_node)];second=B[B.centroid_node.eq(row.unit_node)]
        extra=second[~second.e_id.isin(first.e_id)]
        r=registry[registry.node_id.eq(row.unit_node)].iloc[0]
        reasons=audit[audit.unit_node.eq(row.unit_node)].reason.value_counts().sort_index().to_dict()
        rejected={k:int(v) for k,v in reasons.items() if k not in ['selected','eligible','existing_exit']}
        cid='' if pd.isna(r.centroid_id) else str(int(r.centroid_id))
        if row.kind=='C':cid=cid.zfill(5)
        reference=references[references.centroid_id.eq(float(cid))] if row.kind=='G' else references.iloc[0:0]
        ref=reference.iloc[0] if len(reference)==1 else None
        note='Four valid exits screened' if row.total_valid_exits>=4 else json.dumps(rejected,sort_keys=True)
        if row.total_valid_exits<4 and reasons.get('eligible',0):note+='; remaining individually eligible points do not meet joint 150 m spacing'
        if row.unit_node=='398010':note+='; original 55804 retained as inactive provenance; corrected Clark passenger allocation is 100% to 55797'
        records.append(dict(county_fips=row.county_fips,county_name=NAMES[row.county_fips],unit_node=row.unit_node,
            centroid_id=cid,kind=row.kind,nominal_A=len(first),valid_A=row.native_valid_exits,
            nearest_ref_facility_name='' if ref is None else ref.Facility_Name,
            nearest_ref_facility_type='' if ref is None else ref.Facility_Type,
            invalid_original_retained=len(first)-row.native_valid_exits,new_in_B=row.added_exits,
            nominal_B=len(second),valid_B=row.total_valid_exits,
            original_road_ends=';'.join(sorted(set(first.road_node))),new_road_ends=';'.join(sorted(set(extra.road_node))),
            connector_ids_A=';'.join(first.e_id),connector_ids_B=';'.join(second.e_id),
            why_not_four=note,first_failure_counts=json.dumps(rejected,sort_keys=True)))
    summary=pd.DataFrame(records).sort_values(['county_fips','kind','unit_node'])
    summary.to_csv(out/'node_connector_review.csv',index=False)
    audit.drop(columns='geometry').to_csv(out/'candidate_rejections.csv',index=False)
    details=audit[audit.county_fips.isin(['48039','48071'])].drop(columns='geometry').copy()
    anchors=audit[audit.reason.eq('existing_exit')].drop_duplicates(['unit_node','road_node'])
    details['nearest_original_exit_m']=[
        min(np.hypot(float(r.x)-float(q.x),float(r.y)-float(q.y)) for q in anchors[anchors.unit_node.eq(r.unit_node)].itertuples())
        for r in details.itertuples()]
    details.to_csv(out/'rural_rejection_details.csv',index=False)
    clark=json.loads((out/'clark_allocation_check.json').read_text())
    assert clark['actual_clark_targets']==[{'node':'55788','target':'55797','weight':'1.0'}]
    cp=gpd.GeoDataFrame([dict(road_node=str(x['node_id']),county_fips='53011',allocation_weight=1. if int(x['node_id'])==55797 else 0.,
        reason='connected surviving exit' if int(x['node_id'])==55797 else 'outside largest weak component; not allocated',
        geometry=from_wkb(bytes.fromhex(x['geometry']))) for x in clark['points']],crs=clark['source_crs']).to_crs(roads.crs)
    expected=audit[audit.road_node.astype(str).eq('55797')].geometry.iloc[0]
    assert cp[cp.road_node.eq('55797')].geometry.iloc[0].distance(expected)<1e-6
    target=out/'preflight_findings.gpkg'
    if target.exists() and not a.refresh_maps:raise FileExistsError(target)
    if not target.exists():
        shutil.copyfile(source,target)
        boundary.to_file(target,layer='pilot_county_boundaries',driver='GPKG')
    joined=points.merge(summary,left_on='node_id',right_on='unit_node',how='inner',suffixes=('_inventory',''))
    joined.to_file(target,layer='reviewed_unit_counts',driver='GPKG')
    cp.to_file(target,layer='clark_allocation_check',driver='GPKG')
    # Read-only route diagnosis on the available five-county physical subset.
    # A finite path is evidence of that path; absence does not prove that the
    # full national graph has no route. These are NOT realised OD paths.
    sensitive=pd.to_numeric(roads.faf5_class,errors='coerce').eq(41).fillna(False)
    sensitive|=roads.road_label.astype(str).str.strip().str.lower().isin(['bridge','tunnel','ferry'])
    for col in ['road_bridge','road_tunnel']:sensitive|=roads[col].astype(str).str.strip().str.lower().isin(['yes','true','1','1.0'])
    for col in ['bridge_fraction','tunnel_fraction']:sensitive|=pd.to_numeric(roads[col],errors='coerce').fillna(0).gt(0)
    physical=roads[~sensitive].reset_index(drop=True)
    graph=ig.Graph.TupleList(physical[['from_id','to_id']].astype(str).itertuples(index=False,name=None),directed=False)
    graph.es['metres']=physical.geometry.length.tolist();position={n:i for i,n in enumerate(graph.vs['name'])}
    route_rows=[];route_shapes=[]
    for name,start,end in [('Brazoria opposite carriageway','88897','88898'),('Chambers alternative','111060','111057')]:
        distance=float(graph.distances(position[start],position[end],weights='metres')[0][0])
        record=dict(check=name,from_node=start,to_node=end,structure_free_route_m=distance if np.isfinite(distance) else None,
            within_original_3km_cap=bool(distance<=3000),scope='five-county physical-road subset; diagnostic, not OD path or new connector')
        if np.isfinite(distance):
            edge_indices=graph.get_shortest_paths(position[start],to=position[end],weights='metres',output='epath')[0]
            record['physical_edge_ids']=';'.join(physical.iloc[edge_indices].e_id.astype(str))
            parts=[]
            for geom in physical.iloc[edge_indices].geometry:parts.extend(list(geom.geoms) if geom.geom_type=='MultiLineString' else [geom])
            route_shapes.append({**record,'geometry':MultiLineString([list(x.coords) for x in parts])})
        route_rows.append(record)
    pd.DataFrame(route_rows).to_csv(out/'rural_access_route_diagnostic.csv',index=False)
    if route_shapes:gpd.GeoDataFrame(route_shapes,geometry='geometry',crs=roads.crs).to_file(target,layer='rural_physical_route_diagnostic',driver='GPKG')
    maps=[]
    def draw(name,title,fips,bounds=None,unit_filter=None):
        f,ax=plt.subplots(figsize=(11.5,8))
        polygon=boundary[boundary.GEOID.eq(fips)]
        if bounds is None:
            b=polygon.total_bounds;pad=max(b[2]-b[0],b[3]-b[1])*.04
            bounds=(b[0]-pad,b[1]-pad,b[2]+pad,b[3]+pad)
        window=box(*bounds)
        rr=roads.iloc[roads.sindex.query(window,predicate='intersects')]
        if len(rr):rr.plot(ax=ax,color='#aab2b9',linewidth=.7,zorder=1,label='Modeled physical roads')
        polygon.boundary.plot(ax=ax,color='#777777',linewidth=.8,linestyle=':',zorder=0)
        ids=set(summary.loc[summary.county_fips.eq(fips),'unit_node']) if unit_filter is None else set(unit_filter)
        oo=old[old.from_id.isin(ids)];nn=new[new.from_id.isin(ids)]
        if len(oo):oo.plot(ax=ax,color='#8b55a2',linewidth=1.,linestyle='--',label='Existing virtual connectors',zorder=2)
        if len(nn):nn.plot(ax=ax,color='#008c95',linewidth=1.5,label='Proposed virtual access COST PROXIES',zorder=3)
        aa=audit[audit.unit_node.isin(ids)].drop_duplicates(['road_node','reason'])
        for reason,group in aa.groupby('reason'):
            group.plot(ax=ax,color=COLORS.get(reason,'#777777'),markersize=22 if reason=='selected' else 14,
                label=reason.replace('_',' '),zorder=5)
        pp=points[points.node_id.isin(ids)]
        if len(pp):pp.plot(ax=ax,color='#1e2933',marker='*',markersize=85,zorder=6,label='Demand-unit centroid')
        labelset=pp if unit_filter is None else aa.drop_duplicates('road_node')
        labelcol='node_id' if unit_filter is None else 'road_node'
        for row in labelset.itertuples():
            if not window.covers(row.geometry):continue
            text=str(getattr(row,labelcol))
            neighbors=labelset[labelset.geometry.distance(row.geometry)<max(100.,(bounds[2]-bounds[0])*.035)]
            left=len(neighbors)>1 and row.geometry.x<=float(neighbors.geometry.x.mean())
            offset=(-7,-11) if left else (7,9)
            ax.annotate(text,(row.geometry.x,row.geometry.y),xytext=offset,textcoords='offset points',fontsize=7,
                ha='right' if left else 'left',arrowprops=dict(arrowstyle='-',color='#707b83',lw=.5),
                bbox=dict(facecolor='white',edgecolor='none',alpha=.9,pad=.6),zorder=8)
        if unit_filter is not None:
            labeled=set()
            for row in rr.itertuples():
                roadname=str(row.Road_Name)
                mid=row.geometry.interpolate(.5,normalized=True)
                if roadname in labeled or roadname.upper() in ['RAMP','NONE','NAN',''] or roadname.startswith('L-') or not window.covers(mid):continue
                labeled.add(roadname)
                ax.annotate(roadname,(mid.x,mid.y),fontsize=7,color='#58636b',zorder=4)
                if len(labeled)>=6:break
        ax.set_xlim(bounds[0],bounds[2]);ax.set_ylim(bounds[1],bounds[3]);ax.set_aspect('equal');ax.axis('off')
        ax.set_title(title+'\nPREPARATION ONLY — no A/B assignment results',loc='left',fontsize=13,pad=12)
        handles,labels=ax.get_legend_handles_labels()
        if handles:ax.legend(handles,labels,loc='upper left',bbox_to_anchor=(1.01,1),fontsize=7,frameon=False)
        f.text(.02,.015,'FAF modeled roads only; omitted local streets are not shown. Virtual lines are not physical roads or observed gates.\nPoints show the first failed screen; a rejected point can fail more than one rule.',fontsize=8)
        f.subplots_adjust(left=.02,right=.75,bottom=.09,top=.9)
        path=out/(name+'.png');f.savefig(path,dpi=160,bbox_inches='tight',facecolor='white');plt.close(f)
        maps.append((title,path.name))
    for fips,name in NAMES.items():draw('county_'+fips,name+' — '+fips,fips)
    for name,title,fips,ids in [
        ('brazoria_county_access','Brazoria C node 393038: 88898 is only 48.2 m from existing 88897','48039',['393038']),
        ('brazoria_facility_access','Brazoria G node 445114: cut-edge constraints','48039',['445114']),
        ('chambers_county_access','Chambers C node 393070: eligible 111057 is 3.394 km by road','48071',['393070'])]:
        sub=audit[audit.unit_node.isin(ids)]
        b=sub.total_bounds;pad=500.
        draw(name,title,fips,(b[0]-pad,b[1]-pad,b[2]+pad,b[3]+pad),ids)
    coverage=pd.read_csv(out/'county_coverage.csv',dtype={'county_fips':str})
    decision=dict(recommendation='NEITHER',network_frozen=False,assignment_jobs_submitted=0,
        status='stopped at preregistered county coverage gate',preparation_job=3797277,
        regression_tests_passed=44,positive_units=int(len(summary)),modified_units=int(summary.new_in_B.gt(0).sum()),
        added_virtual_exits=int(summary.new_in_B.sum()),failed_counties=['48039','48071'])
    (out/'decision.json').write_text(json.dumps(decision,indent=2))
    images=''.join('<section><h2>'+html.escape(title)+'</h2><img alt="'+html.escape(title)+'" src="data:image/png;base64,'+base64.b64encode((out/path).read_bytes()).decode()+'"></section>' for title,path in maps)
    table=summary[['county_name','unit_node','centroid_id','kind','nearest_ref_facility_name','nominal_A','valid_A','new_in_B','nominal_B','valid_B','original_road_ends','new_road_ends','why_not_four']].to_html(index=False,escape=True,border=0)
    page='''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>A/B connector preflight — stopped at coverage gate</title><style>body{font:16px/1.5 system-ui,sans-serif;margin:32px;color:#192b38;background:#f7f9fa;max-width:1600px}h1,h2{line-height:1.2}section{background:white;border:1px solid #d5dfe5;padding:20px;margin:24px 0}img{display:block;width:100%;height:auto;min-height:160px}table{border-collapse:collapse;font-size:12px;width:100%}td,th{border:1px solid #d8e1e7;padding:7px;text-align:left;vertical-align:top}th{background:#eaf0f4;position:sticky;top:0}.table{overflow:auto}strong{color:#a52c28}a{color:#006c89}</style><h1>A/B connector pilot: preparation stopped</h1><p><strong>No assignment jobs submitted. No network frozen. Neither A nor B selected.</strong></p><p>The fixed screen found 41 additional virtual exits at 15 of 26 positive-demand units. LA, Harris and Clark have modifications. Brazoria and Chambers fail the preregistered county-coverage gate.</p><p>Chambers has an otherwise eligible point 3,393.8 m away by the screened road route, beyond the 3,000 m cap. Brazoria's county intake has only a near-duplicate point and a bridge/ramp-only point; the G node's alternatives bypass physical cut edges. These are geometry-screen findings, not convergence, isolation or FAF agreement results.</p><p>This file embeds all maps as PNGs and requires no JavaScript, map tiles or internet access. For pan/zoom and attributes, open <a href="preflight_findings.gpkg">preflight_findings.gpkg</a> in GIS software. <a href="node_connector_review.csv">Node/connector CSV</a> · <a href="rural_rejection_details.csv">Rural rejection details</a></p><h2>Coverage</h2>'''+coverage.to_html(index=False,border=0)+images+'<h2>Every tested loading unit</h2><p>unit_node is the graph vertex ID; centroid_id is FAF’s logical centroid identifier. They are different keys. P_alias is a computational passenger endpoint, not an additional facility. Nominal counts include retained inactive original records; valid counts exclude disconnected ends. “Why not four” records the first failed screens, not an exhaustive proof of real-world access.</p><div class="table">'+table+'</div></html>'
    (out/'index.html').write_text(page,encoding='utf-8')
    print(json.dumps(decision,indent=2));print('MAPS',len(maps),'HTML_BYTES',(out/'index.html').stat().st_size)

if __name__=='__main__':main()
