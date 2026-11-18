"""Compare saved, gated A/B outputs; never tune exits or launch assignments."""
from pathlib import Path
import argparse,json
import numpy as np,pandas as pd,duckdb

COUNTIES=['06037','48201','53011','48039','48071']
DAYS=[0,7,14,30,60,90]

def compare(root,ops):
    inputs=ops/'inputs';pre=json.loads((inputs/'preflight.json').read_text())
    assert pre['coverage_pass'] and pre['same_OD_between_arms']
    db=duckdb.connect();db.execute('SET threads=4');db.execute("SET memory_limit='40GB'")
    registry=pd.read_csv(inputs/'node_registry.csv',dtype={'node_id':str,'county_fips':str})
    assert registry.node_id.is_unique
    units=registry[registry.county_fips.isin(COUNTIES)&registry.kind.isin(['C','S','G','P_alias'])].copy()
    for arm,label in [('A','A'),('B','B4')]:
        mapping=pd.read_csv(inputs/f'connectors_{label}.csv',dtype=str)
        units=units.merge(mapping.groupby('centroid_node').size().rename(f'nominal_exits_{arm}'),left_on='node_id',right_index=True,how='left')
    coverage=pd.read_csv(inputs/'unit_coverage.csv',dtype={'unit_node':str})
    units=units.merge(coverage[['unit_node','native_valid_exits','added_exits','total_valid_exits','reason']],left_on='node_id',right_on='unit_node',how='left',validate='one_to_one')
    units['retained_invalid_original_exits']=units.nominal_exits_A-units.native_valid_exits
    units['reason']=units.reason.fillna('not_selected_by_positive_control_loading; connectivity_not_reaudited')
    units.to_csv(ops/'connector_counts_and_exceptions.csv',index=False)
    db.register('registry',registry[['node_id','county_fips','kind']])
    def paired_cohort(post,intact):
        # County totals alone could hide swapped OD quantities within a county.
        q='''WITH a AS (
               SELECT CAST(origin_node AS VARCHAR) o,CAST(destination_node AS VARCHAR) d,sum(flow) f
               FROM read_parquet(?) WHERE flow>0 GROUP BY o,d),
             b AS (
               SELECT CAST(origin_node AS VARCHAR) o,CAST(destination_node AS VARCHAR) d,sum(flow) f
               FROM read_parquet(?) WHERE flow>0 GROUP BY o,d)
             SELECT count(*) FROM a FULL JOIN b USING(o,d)
             WHERE abs(coalesce(a.f,0)-coalesce(b.f,0))>
                   greatest(abs(coalesce(a.f,0)),abs(coalesce(b.f,0)),1.)*1e-9'''
        bad=db.execute(q,[str(post),str(intact)]).fetchone()[0]
        assert bad==0,f'paired cohort mismatch: {bad} OD pairs differ in {post}'
    def sums(path,metric):
        assert path.is_file(),path
        schema=dict(row[:2] for row in db.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(path)]).fetchall())
        if metric=='cost':
            costs=['operating_cost_per_flow','time_cost_per_flow','toll_cost_per_flow']
            assert set(costs)<=set(schema),f'Missing road cost components in {path}'
            invalid=' OR '.join(f'{c} IS NULL OR NOT isfinite({c})' for c in costs)
            assert db.execute(f'SELECT count(*) FROM read_parquet(?) WHERE flow>0 AND ({invalid})',[str(path)]).fetchone()[0]==0,f'Invalid road costs in {path}'
        flow='flow' if 'flow' in schema else 'Car21'
        amount=flow if metric=='isolation' else flow+' * ('+' + '.join('COALESCE('+c+',0)' for c in ['operating_cost_per_flow','time_cost_per_flow','toll_cost_per_flow','fare_cost_per_flow'] if c in schema)+')'
        data={}
        for end in ['origin','destination']:
            q=f'''SELECT r.county_fips,sum({amount}) AS metric_total,sum({flow}) AS flow_total
                  FROM read_parquet(?) p LEFT JOIN registry r
                  ON CAST(p.{end}_node AS VARCHAR)=r.node_id
                  WHERE p.{flow}>0 GROUP BY r.county_fips'''
            rows=db.execute(q,[str(path)]).fetchall()
            for fips,value,trips in rows:data[(end,fips or 'UNRESOLVED')]=(float(value or 0),float(trips or 0))
        return data
    records=[];unresolved=[];diagnostics=[];freight_edges={}
    for case in ['freight','combined']:
        for arm in ['A','B']:
            reused=case=='freight' and arm=='A'
            v='conus_connector_test2g_gateway' if reused else f'ab_connector_{case}_{arm}_20261118'
            recovery=v+'_virtual_exempt' if reused else v
            run=ops/v
            if not reused:
                for stage in ['baseline','hazard','damage','completion']:
                    assert (run/f'{stage}_verified.json').is_file(),(v,stage)
                baseline_audit=(run/'baseline_shortcuts.log').read_text()
                assert 'shortcuts=0, share=0.0' in baseline_audit
            audit=(root/'stage2_scripts/virtual_exemption_reruns_20261118'/recovery/'recovery_shortcuts.log') if reused else run/'recovery_shortcuts.log'
            lines=audit.read_text().splitlines()
            assert len(lines)==12 and all('shortcuts=0, share=0.0' in x for x in lines)
            base=sums(root/'results'/v/'trip_isolations.pq','isolation')
            out=root/'results/rerouting_analysis'/recovery/'304/1'
            for day in DAYS:
                iso=sums(out/f'trip_isolations_{case}_s1_day{day}.pq','isolation')
                paired_cohort(out/f'odpfc_{case}_s1_day{day}.pq',out/f'odpfc_{case}_s1_day{day}_baseline.pq')
                post=sums(out/f'odpfc_{case}_s1_day{day}.pq','cost')
                intact=sums(out/f'odpfc_{case}_s1_day{day}_baseline.pq','cost')
                for end in ['origin','destination']:
                    for fips in COUNTIES:
                        key=(end,fips);baseline_iso=base.get(key,(0,0))[0];hazard_iso=iso.get(key,(0,0))[0]
                        pc,pf=post.get(key,(0,0));bc,bf=intact.get(key,(0,0))
                        # The paired intact solve must serve the same cohort.
                        np.testing.assert_allclose(pf,bf,rtol=1e-9,atol=1e-6,err_msg=f'{v}/{day}/{key} paired cohort mismatch')
                        records.append(dict(case=case,arm=arm,county_fips=fips,day=day,end=end,
                            baseline_isolation=baseline_iso,hazard_isolation=hazard_iso,total_isolation=baseline_iso+hazard_iso,
                            rerouting_cost_usd_day=pc-bc,routed_disrupted_flow=pf,
                            isolation_units='trucks/day' if case=='freight' else 'PCE/day'))
                    for name,data in [('baseline_isolation',base),('hazard_isolation',iso),('post_cost',post),('intact_cost',intact)]:
                        value,trips=data.get((end,'UNRESOLVED'),(0,0))
                        unresolved.append(dict(case=case,arm=arm,day=day,end=end,metric=name,value=value,flow=trips))
            edge=pd.read_parquet(root/'results'/v/'edge_flows.gpq',columns=['e_id','acc_flow','current_capacity','length_mile'])
            links=pd.read_csv(inputs/f"connectors_{'A' if arm=='A' else 'B4'}.csv",dtype=str)
            endpoints=set(links.road_node)
            # Road saturation near loading is joined using physical endpoints,
            # never virtual connector capacity as an additional physical lane.
            raw=pd.read_parquet(inputs/f"network_{'A' if arm=='A' else 'B4'}.gpq",columns=['e_id','from_id','to_id','faf5_class'])
            physical_mask=~pd.to_numeric(raw.faf5_class,errors='coerce').eq(50).fillna(False)
            near=raw[physical_mask&(raw.from_id.astype(str).isin(endpoints)|raw.to_id.astype(str).isin(endpoints))]
            local=edge.merge(near[['e_id']],on='e_id',validate='one_to_one')
            vc=local.acc_flow/local.current_capacity.replace(0,np.nan)
            physical_ids=set(raw.loc[physical_mask,'e_id'])
            physical=edge[edge.e_id.isin(physical_ids)]
            if case=='freight':freight_edges[arm]=physical[['e_id','acc_flow']].rename(columns={'acc_flow':f'flow_{arm}'})
            diagnostics.append(dict(case=case,arm=arm,loading_adjacent_physical_links=len(local),
                binding_links=int(vc.ge(1-1e-9).sum()),vc_p95=float(vc.quantile(.95)),vc_max=float(vc.max()),
                baseline_physical_flow_miles=float((physical.acc_flow*physical.length_mile).sum()),
                flow_mile_units='truck-miles/day' if case=='freight' else 'PCE-miles/day'))
    df=pd.DataFrame(records);df.to_csv(ops/'county_primary_metrics.csv',index=False)
    keys=['case','county_fips','day','end','isolation_units']
    wide=df[df.arm.eq('A')].drop(columns='arm').merge(df[df.arm.eq('B')].drop(columns='arm'),on=keys,suffixes=('_A','_B'),validate='one_to_one')
    wide['isolation_difference']=wide.total_isolation_B-wide.total_isolation_A
    wide['isolation_relative_effect']=wide.isolation_difference.abs()/np.maximum(wide.total_isolation_A.abs(),100.)
    wide['cost_difference_usd_day']=wide.rerouting_cost_usd_day_B-wide.rerouting_cost_usd_day_A
    wide['cost_relative_effect']=wide.cost_difference_usd_day.abs()/np.maximum(wide.rerouting_cost_usd_day_A.abs(),10000.)
    wide['material']=wide.isolation_relative_effect.ge(.05)|wide.cost_relative_effect.ge(.05)
    wide['served_cohort_difference']=wide.routed_disrupted_flow_B-wide.routed_disrupted_flow_A
    wide.to_csv(ops/'county_AB_comparison.csv',index=False)
    pd.DataFrame(unresolved).to_csv(ops/'unresolved_county_metrics.csv',index=False)
    pd.DataFrame(diagnostics).to_csv(ops/'loading_saturation.csv',index=False)
    official=pd.read_parquet(root/'stage2_scripts/connector_test2_conus/official_roads.pq')
    assert official.official.dropna().ge(0).all(),'Invalid published-flow sentinel must not be reported as zero'
    official['e_id']=official.link_id.astype(str)
    scores=freight_edges['A'].merge(freight_edges['B'],on='e_id',validate='one_to_one')
    scores=scores.merge(official[['e_id','official','CTFIPS']],on='e_id',how='left',validate='one_to_one')
    scores['county_fips']=scores.CTFIPS.map(lambda x:f'{int(x):05}' if pd.notna(x) else None)
    scores['official_status']=np.where(scores.official.isna(),'missing_record',np.where(scores.official.gt(0),'positive','zero'))
    scores['absolute_error_change']=(scores.flow_B-scores.official).abs()-(scores.flow_A-scores.official).abs()
    scores.to_csv(ops/'physical_baseline_FAF22_link_comparison.csv',index=False)
    faf_metrics=[]
    for scope in ['CONUS']+COUNTIES:
        group=scores if scope=='CONUS' else scores[scores.county_fips.eq(scope)]
        matched=group[group.official.notna()]
        for arm in ['A','B']:
            modeled=matched[f'flow_{arm}'];den=float(matched.official.sum())
            faf_metrics.append(dict(scope=scope,arm=arm,links_compared=len(matched),missing_official_records=int(group.official.isna().sum()),
                explicit_official_zeros=int(matched.official.eq(0).sum()),pearson=modeled.corr(matched.official) if len(matched)>1 and modeled.nunique()>1 and matched.official.nunique()>1 else None,
                wape=float((modeled-matched.official).abs().sum())/den if den else None,
                modeled_link_traversals_day=float(modeled.sum()),official_link_traversals_day=den,
                scope_note='Freight baseline only; combined PCE is not compared with official trucks. Link traversals are not generated trips.'))
    pd.DataFrame(faf_metrics).to_csv(ops/'FAF22_baseline_diagnostics.csv',index=False)
    decision=dict(recommendation='B' if wide.material.any() else 'A',frozen=False,
        material_cells=int(wide.material.sum()),total_cells=len(wide),mechanical_gates='passed',
        interpretation='B is an access-cost screening experiment, not verified new physical access. Owner review precedes any freeze.',
        limitations=['Harvey tests Texas directly; LA/Clark effects are congestion and through-trips.',
                    'Combined monetary costs use the current single-cost PCE approximation.',
                    'Origin and destination are separate views; do not add them as unique trips.',
                    'Isolation includes baseline failures; rerouting costs exclude isolated trips.',
                    'Cross-arm served-cohort differences are reported explicitly.',
                    'Unresolved county attribution is retained separately.'])
    (ops/'decision.json').write_text(json.dumps(decision,indent=2));print(json.dumps(decision,indent=2))
    db.close()

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);p.add_argument('--ops',type=Path,required=True)
    a=p.parse_args()
    try:compare(a.root,a.ops)
    except Exception as e:
        (a.ops/'decision.json').write_text(json.dumps({'recommendation':'NEITHER','frozen':False,'mechanical_gates':'failed','error':str(e)},indent=2))
        raise
