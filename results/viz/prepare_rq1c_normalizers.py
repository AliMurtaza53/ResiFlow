from pathlib import Path
import pandas as pd
import pyarrow.parquet as pq
root=Path('C:/Users/akothaw/Desktop/data/soge_clusters')
links=pd.read_parquet(root/'networks/faf5/faf5_road_links.gpq',columns=['e_id','STATE','length','lanes']).drop_duplicates('e_id')
assert links['length'].ge(0).all() and links.lanes.ge(0).all()
links['lane_miles']=links['length']*links.lanes/1609.344
lanes=links.groupby('STATE').lane_miles.sum()
freight=pd.Series(dtype=float)
for batch in pq.ParquetFile(root/'census_datasets/faf5_od_matrix_by_sctg.pq').iter_batches(batch_size=500000,columns=['origin_detail_zone','value']):
 d=batch.to_pandas(); d['fips']=d.origin_detail_zone.astype(str).str.zfill(5).str[:2]
 freight=freight.add(d.groupby('fips').value.sum(),fill_value=0)
states={'Texas':('TX','48'),'Louisiana':('LA','22'),'Mississippi':('MS','28'),'Missouri':('MO','29'),'Arkansas':('AR','05'),'Tennessee':('TN','47'),'West Virginia':('WV','54'),'Kentucky':('KY','21'),'Virginia':('VA','51'),'New York':('NY','36'),'Pennsylvania':('PA','42')}
rows=[]
for name,(abbr,fips) in states.items():
 rows.append(dict(state=name,lane_miles=lanes[abbr],freight_value_dollars=freight[fips]*1e6*304.702/245.120,freight_basis='annual outbound truck freight, 2022 flows, CPI adjusted 2017 to 2023 dollars'))
pd.DataFrame(rows).to_csv('results/viz/rq1c_state_normalizers.csv',index=False)
print(pd.DataFrame(rows).to_string(index=False))

