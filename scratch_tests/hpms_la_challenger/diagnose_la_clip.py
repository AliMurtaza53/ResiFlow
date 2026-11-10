import pyogrio
import pandas as pd
from pathlib import Path

COUNTY = Path(r"C:/Users/akothaw/Desktop/data/faf5_data/county_shp/tl_2022_us_county.shp")
HPMS = "/vsizip/C:/Users/akothaw/Desktop/data/faf5_data/HPMS2024.zip/HPMS2024.gdb"
la = pyogrio.read_dataframe(COUNTY, where="GEOID='06037'", columns=["GEOID"])
bbox = tuple(la.total_bounds)
raw = pyogrio.read_dataframe(
    HPMS,
    layer="HPMS_FULL_CA_2024",
    bbox=bbox,
    columns=["f_system", "through_lanes", "county_id", "structure_type"],
)
print("bbox n", len(raw))
print("county_id value_counts head:\n", raw["county_id"].value_counts(dropna=False).head(15))
print("bbox f_system:\n", raw["f_system"].value_counts(dropna=False))
la37 = raw[raw["county_id"].astype("Int64") == 37]
print("\ncounty_id==37 n", len(la37))
print("f_system:\n", la37["f_system"].value_counts(dropna=False))
lanes = pd.to_numeric(la37["through_lanes"], errors="coerce")
print("lanes null/<=0 by f_system:")
print(la37.assign(bad=lanes.isna() | (lanes <= 0)).groupby("f_system")["bad"].agg(["sum", "count"]))
la_geom = la.to_crs(raw.crs).geometry.iloc[0]
spatial = raw[raw.intersects(la_geom)]
print("\nspatial-only n", len(spatial))
print("spatial f_system:\n", spatial["f_system"].value_counts(dropna=False))
print("spatial county_id top:\n", spatial["county_id"].value_counts(dropna=False).head(10))
