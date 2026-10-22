"""Baseline freight mix (share of FAF5 truck flow by SCTG group) over each event's affected states.

Denominator for the RQ3 A exposure ratio: disrupted-cost share / baseline-flow share. Baseline flow = FAF5
county OD truck trips (the same Car21 flow variable the industry-mix script weights by) for OD pairs whose
origin or destination county lies in the event's affected states. Tons and value are kept for reference.
"""
import sys
from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq
import build_advisor_review_figures as b

DEFAULT_SRC = Path(r'C:\Users\akothaw\Desktop\data\soge_clusters\census_datasets\faf5_county_od.pq')
OUT = b.VIZ_DIR / 'rq3_baseline_mix_by_event.csv'
FIPS = {'Texas':'48','Louisiana':'22','Mississippi':'28','Arkansas':'05','Oklahoma':'40','Missouri':'29',
        'Tennessee':'47','Illinois':'17','Kentucky':'21','West Virginia':'54','Virginia':'51',
        'North Carolina':'37','New York':'36','Pennsylvania':'42','Maryland':'24','New Jersey':'34'}

def main(src=DEFAULT_SRC):
    states = {h: {FIPS[s] for s in b.STATE_POOL[h]} for h in b.HAZARDS}
    parts = []
    for batch in pq.ParquetFile(src).iter_batches(batch_size=2_000_000,
            columns=['origin_county','destination_county','sctgG5','tons','value','daily_truck_trips']):
        df = batch.to_pandas()
        origin, dest = df.origin_county.str[:2], df.destination_county.str[:2]
        for hazard, fips in states.items():
            touched = df[origin.isin(fips) | dest.isin(fips)]
            part = touched.groupby('sctgG5')[['tons','value','daily_truck_trips']].sum().reset_index()
            part['hazard'] = hazard
            parts.append(part)
    out = pd.concat(parts).groupby(['hazard','sctgG5'], as_index=False).sum()
    out['industry'] = out.sctgG5.map({'sctg0109':'Agriculture, fishing, forestry','sctg1014':'Mining',
        'sctg1519':'Petroleum & coal products','sctg2033':'Manufactured goods','sctg3499':'Mixed freight & other'})
    out['share_trips'] = out.groupby('hazard').daily_truck_trips.transform(lambda s: s / s.sum())
    out.to_csv(OUT, index=False)
    print(out.pivot(index='hazard', columns='industry', values='share_trips').round(3))

if __name__ == '__main__':
    main(*(Path(a) for a in sys.argv[1:]))
