"""Compare saved, gated A/B outputs; never tune exits or launch assignments."""
from pathlib import Path
import argparse,json
import duckdb,numpy as np,pandas as pd

COUNTIES=['06037','48201','53011','48039','48071']
DAYS=[0,7,14,30,60,90]

def compare(root,ops):
    inputs=ops/'inputs';pre=json.loads((inputs/'preflight.json').read_text())
    assert pre['coverage_pass'] and pre['same_OD_between_arms']
    db=duckdb.connect();db.execute('SET threads=4');db.execute("SET memory_limit='40GB'")
    registry=pd.read_csv(inputs/'node_registry.csv',dtype={'node_id':str,'county_fips':str})
    assert registry.node_id.is_unique
    db.register('registry',registry[['node_id','county_fips','kind']])
    def sums(path,metric):
        assert path.is_file(),path
        schema=dict(row[:2] for row in db.execute('DESCRIBE SELECT * FROM read_parquet(?)',[str(path)]).fetchall())
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
    records=[];unresolved=[];diagnostics=[]
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
            edge=pd.read_parquet(root/'results'/v/'edge_flows.gpq',columns=['e_id','acc_flow','current_capacity'])
            links=pd.read_csv(inputs/f"connectors_{'A' if arm=='A' else 'B4'}.csv",dtype=str)
            endpoints=set(links.road_node)
            # Road saturation near loading is joined using physical endpoints,
            # never virtual connector capacity as an additional physical lane.
            raw=pd.read_parquet(inputs/f"network_{'A' if arm=='A' else 'B4'}.gpq",columns=['e_id','from_id','to_id','faf5_class'])
            near=raw[(pd.to_numeric(raw.faf5_class,errors='coerce')!=50)&(raw.from_id.astype(str).isin(endpoints)|raw.to_id.astype(str).isin(endpoints))]
            local=edge.merge(near[['e_id']],on='e_id',validate='one_to_one')
            vc=local.acc_flow/local.current_capacity.replace(0,np.nan)
            diagnostics.append(dict(case=case,arm=arm,loading_adjacent_physical_links=len(local),
                binding_links=int(vc.ge(1-1e-9).sum()),vc_p95=float(vc.quantile(.95)),vc_max=float(vc.max())))
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
