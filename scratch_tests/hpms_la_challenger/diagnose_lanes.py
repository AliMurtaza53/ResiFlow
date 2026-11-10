import pyogrio
import pandas as pd
from pathlib import Path

COUNTY = Path(r"C:/Users/akothaw/Desktop/data/faf5_data/county_shp/tl_2022_us_county.shp")
HPMS = "/vsizip/C:/Users/akothaw/Desktop/data/faf5_data/HPMS2024.zip/HPMS2024.gdb"
la = pyogrio.read_dataframe(COUNTY, where="GEOID='06037'", columns=["GEOID"])
raw = pyogrio.read_dataframe(
    HPMS,
    layer="HPMS_FULL_CA_2024",
    bbox=tuple(la.total_bounds),
    columns=["f_system", "through_lanes", "county_id"],
)
la_geom = la.to_crs(raw.crs).geometry.iloc[0]
s = raw[raw.intersects(la_geom)]
lanes = pd.to_numeric(s["through_lanes"], errors="coerce")
print(s.assign(bad=lanes.isna() | (lanes <= 0)).groupby("f_system")["bad"].agg(["sum", "count", "mean"]))
