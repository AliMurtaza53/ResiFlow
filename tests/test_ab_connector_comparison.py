"""Accounting regression: include pre-event failures and preserve paired cohorts."""
import importlib.util,json
from pathlib import Path
import pandas as pd
import pytest

spec=importlib.util.spec_from_file_location('ab_compare',Path(__file__).parents[1]/'scripts/diagnostics/compare_ab_connector_pilot.py')
mod=importlib.util.module_from_spec(spec);spec.loader.exec_module(mod)

def setup_case(tmp_path,cohort_mismatch=False):
    root=tmp_path/'root';ops=tmp_path/'ops';inp=ops/'inputs';inp.mkdir(parents=True)
    ref=root/'stage2_scripts/connector_test2_conus';ref.mkdir(parents=True)
    pd.DataFrame({'link_id':['r'],'official':[80.],'CTFIPS':[6037]}).to_parquet(ref/'official_roads.pq')
    (inp/'preflight.json').write_text(json.dumps({'coverage_pass':True,'same_OD_between_arms':True}))
    pd.DataFrame({'node_id':['1','2'],'county_fips':['06037','48201'],'kind':['C','C']}).to_csv(inp/'node_registry.csv',index=False)
    for arm in ['A','B4']:
        pd.DataFrame({'e_id':['v'],'centroid_node':['1'],'road_node':['3']}).to_csv(inp/f'connectors_{arm}.csv',index=False)
        pd.DataFrame({'e_id':['r'],'from_id':['3'],'to_id':['4'],'faf5_class':[14]}).to_parquet(inp/f'network_{arm}.gpq')
    for case in ['freight','combined']:
        for arm in ['A','B']:
            reused=case=='freight' and arm=='A'
            v='conus_connector_test2g_gateway' if reused else f'ab_connector_{case}_{arm}_20261118'
            recovery=v+'_virtual_exempt' if reused else v
            run=ops/v;run.mkdir()
            for stage in ['baseline','hazard','damage','completion']:(run/f'{stage}_verified.json').write_text('{}')
            (run/'baseline_shortcuts.log').write_text('shortcuts=0, share=0.0')
            audit=root/'stage2_scripts/virtual_exemption_reruns_20261118'/recovery if reused else run
            audit.mkdir(parents=True,exist_ok=True)
            (audit/'recovery_shortcuts.log').write_text(('shortcuts=0, share=0.0\n')*12)
            base=root/'results'/v;base.mkdir(parents=True)
            pd.DataFrame({'e_id':['r'],'acc_flow':[100.],'current_capacity':[100.],'length_mile':[2.]}).to_parquet(base/'edge_flows.gpq')
            iso=pd.DataFrame({'origin_node':['1'],'destination_node':['2'],'flow':[2.]})
            iso.to_parquet(base/'trip_isolations.pq')
            out=root/'results/rerouting_analysis'/recovery/'304/1';out.mkdir(parents=True)
            for day in mod.DAYS:
                iso.assign(flow=3.).to_parquet(out/f'trip_isolations_{case}_s1_day{day}.pq')
                cost=pd.DataFrame({'origin_node':['1'],'destination_node':['2'],'flow':[10.],
                    'operating_cost_per_flow':[0.],'time_cost_per_flow':[10. if arm=='A' else 60.],'toll_cost_per_flow':[0.]})
                cost.to_parquet(out/f'odpfc_{case}_s1_day{day}.pq')
                cost.assign(flow=9. if cohort_mismatch and arm=='B' else 10.,time_cost_per_flow=0.).to_parquet(out/f'odpfc_{case}_s1_day{day}_baseline.pq')
    return root,ops

def test_baseline_failures_count_and_boundary_is_material(tmp_path):
    root,ops=setup_case(tmp_path);mod.compare(root,ops)
    metrics=pd.read_csv(ops/'county_primary_metrics.csv',dtype={'county_fips':str})
    la=metrics[metrics.county_fips.eq('06037')&metrics.end.eq('origin')]
    assert la.total_isolation.eq(5.).all()  # two baseline failures plus three additional failures
    df=pd.read_csv(ops/'county_AB_comparison.csv',dtype={'county_fips':str})
    la=df[df.county_fips.eq('06037')&df.end.eq('origin')]
    assert la.cost_difference_usd_day.eq(500.).all()
    assert la.material.all()  # exactly $500 at the denominator floor counts
    assert json.loads((ops/'decision.json').read_text())['frozen'] is False

def test_different_paired_served_cohort_fails_gate(tmp_path):
    root,ops=setup_case(tmp_path,cohort_mismatch=True)
    with pytest.raises(AssertionError,match='paired cohort mismatch'):mod.compare(root,ops)
