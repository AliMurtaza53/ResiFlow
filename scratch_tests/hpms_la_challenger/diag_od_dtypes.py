import pandas as pd

od = pd.read_parquet(
    "/scratch/akothaw/multimodal_hazard_data/scratch_tests/hpms_la_challenger/passenger_od_hpms_la.pq"
)
print("dtypes", od.dtypes.to_dict())
print("origin sample", od["origin_node"].head(3).tolist(), type(od["origin_node"].iloc[0]))
print("dest sample", od["destination_node"].head(3).tolist(), type(od["destination_node"].iloc[0]))
for col in ("origin_node", "destination_node"):
    s = od[col]
    hit = s.astype(str).str.match(r"^600")
    print(col, "centroid-ish rows", int(hit.sum()), "sample", s[hit].head(5).tolist())
