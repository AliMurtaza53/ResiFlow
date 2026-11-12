"""Top-15 partner counties per state that send trips to / attract trips from the Harvey-affected counties.
Corrected freight OD (trucks/day, flat 20 t). The affected set is an ASSUMPTION (Houston-area flood footprint), edit AFFECTED."""
import sys, pandas as pd, geopandas as gpd, pyarrow.parquet as pq
D = "C:/Users/akothaw/Desktop"
AFFECTED = {48201: "Harris", 48157: "Fort Bend", 48039: "Brazoria", 48167: "Galveston", 48339: "Montgomery", 48291: "Liberty",
            48071: "Chambers", 48245: "Jefferson", 48361: "Orange", 48199: "Hardin", 48473: "Waller", 48481: "Wharton"}
xw = pd.read_csv(f"{D}/ResiFlow/.worktrees/anaheim-diagnostics/parameters/crosswalks/county_node_crosswalk_conterminous.csv")
n2c = dict(zip(xw.node_id, xw.county_fips))
od = pq.read_table(f"{D}/data/soge_clusters/census_datasets_conterminous/faf5_od_matrix_conterminous.pq").to_pandas()
od["o"] = od.origin_node.astype("int64").map(n2c); od["d"] = od.destination_node.astype("int64").map(n2c)
ao, ad = od.o.isin(AFFECTED), od.d.isin(AFFECTED)
names = gpd.read_file(f"{D}/gis_review/resiflow_od_review.gpkg", layer="county_centroids_tiger")
nm = {int(g): f"{n}" for g, n in zip(names.GEOID, names.NAME)}
inb = od[ad & ~ao].groupby("o").Car21.sum().rename("sends_to_affected")      # partner -> affected
out = od[ao & ~ad].groupby("d").Car21.sum().rename("receives_from_affected")  # affected -> partner
t = pd.concat([inb, out], axis=1).fillna(0); t["total"] = t.sum(axis=1); t["state"] = t.index // 1000
t["county"] = [nm.get(i, str(i)) for i in t.index]; t = t.reset_index(names="fips")
t["rank_in_state"] = t.groupby("state").total.rank(ascending=False, method="first")
top = t[t.rank_in_state <= 15].sort_values(["state", "rank_in_state"])
top.to_csv("C:/Users/akothaw/Desktop/gis_review/harvey_partner_counties_top15_by_state.csv", index=False)
within = od[ao & ad].Car21.sum(); tot_ext = t.total.sum()
print(f"affected counties {len(AFFECTED)}: trips among themselves {within:,.0f}/day; with all other counties {tot_ext:,.0f}/day")
s = t.groupby("state").agg(trips=("total", "sum"), counties=("fips", "size")).sort_values("trips", ascending=False)
s["share"] = s.trips / tot_ext; s["cum"] = s.share.cumsum()
print(s.head(20).round(3).to_string()); print("states with any partner:", len(s))
print("top 15 shown covers", f"{top.total.sum()/tot_ext:.1%}", "of external trips")
print(top.sort_values("total", ascending=False).head(15)[["fips", "county", "state", "sends_to_affected", "receives_from_affected", "total"]].round(0).to_string(index=False))
