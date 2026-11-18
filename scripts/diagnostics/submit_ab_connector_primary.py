"""Submit the fixed pilot only AFTER prerequisites and preparation have passed.

This is a one-shot, resumable submission helper, not a scheduler or a freeze
operation. It never retries a failed analysis job or extends the resource cap.
"""
from pathlib import Path
import argparse,json,subprocess
import pandas as pd

def state(job):
    text=subprocess.check_output(['sacct','-j',str(job),'-n','-X','-P','--format=JobID,State,ExitCode'],text=True)
    rows=[x.split('|') for x in text.splitlines() if x.startswith(str(job)+'|')]
    assert len(rows)==1,(job,text)
    return rows[0][1:3]

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True)
    p.add_argument('--preparation-job',required=True);p.add_argument('--submit',action='store_true')
    a=p.parse_args();ops=a.root/'stage2_scripts/ab_connector_pilot_20261118'
    assert state(a.preparation_job)==['COMPLETED','0:0'],'Preparation has not passed; no submission'
    previous=json.loads((a.root/'stage2_scripts/virtual_exemption_reruns_20261118/manifest.json').read_text())
    for row in previous:
        assert state(row['job_id'])==['COMPLETED','0:0'],row
        lines=(Path(row['script']).parent/'recovery_shortcuts.log').read_text().splitlines()
        assert len(lines)==12 and all('shortcuts=0, share=0.0' in x for x in lines)
    pre=json.loads((ops/'inputs/preflight.json').read_text())
    assert pre['coverage_pass'] and pre['same_OD_between_arms']
    coverage=pd.read_csv(ops/'inputs/county_coverage.csv',dtype={'county_fips':str})
    assert set(coverage.county_fips)=={'06037','48201','53011','48039','48071'}
    assert coverage.modified_units.gt(0).all()
    screen=pd.read_csv(ops/'inputs/screening_path_time_range.csv')
    assert len(screen)==5 and screen.centroid_shortcuts.eq(0).all()
    manifest_path=ops/'primary_manifest.json';manifest=json.loads(manifest_path.read_text())
    assert len(manifest)==3
    assert {(x['case'],x['arm']) for x in manifest}=={('freight','B'),('combined','A'),('combined','B')}
    if not a.submit:
        print('All prerequisites passed; dry run only');return
    def submit(script,dependency=None):
        cmd=['sbatch','--parsable','--kill-on-invalid-dep=yes']
        if dependency:cmd+=['--dependency=afterok:'+str(dependency)]
        return subprocess.check_output(cmd+[script],text=True).strip().split(';')[0]
    for row in manifest:
        if 'baseline_job_id' not in row:
            row['baseline_job_id']=submit(row['baseline_script'])
            manifest_path.write_text(json.dumps(manifest,indent=2))
        if 'recovery_job_id' not in row:
            row['recovery_job_id']=submit(row['recovery_script'],row['baseline_job_id'])
            row['status']='submitted';manifest_path.write_text(json.dumps(manifest,indent=2))
    comparison=ops/'comparison_submission.json'
    if not comparison.exists():
        job=submit(str(ops/'comparison.slurm'),':'.join(x['recovery_job_id'] for x in manifest))
        comparison.write_text(json.dumps({'job_id':job,'frozen':False,'preparation_job_id':a.preparation_job},indent=2))
    print(manifest_path.read_text());print(comparison.read_text())

if __name__=='__main__':main()
