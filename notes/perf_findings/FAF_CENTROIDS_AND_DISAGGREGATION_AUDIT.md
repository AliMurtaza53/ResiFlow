# Audit: county disaggregation against the BTS guide, and the FAF5 centroids

Written 2026-11-11. Sources: BTS "FAF5 Experimental County-Level Estimates: Technical Report" (User Guide, pp. 38-41), FAF5 User's Guide,
`FAF5 Network Data Dictionary.pdf` (local, `Desktop\data\faf5_data\network_data\`), the native `FAF5Network.gdb`, and the June 19 build record.

## 1. Was the disaggregation done by the book? Yes, with two deviations

BTS procedure: filter FAF rows by mode; collapse SCTG to five groups; join the origin factor on (`dms_orig`, `sctgG5`) and the destination factor on
(`dms_dest`, `sctgG5`); county tons = FAF tons x `f_orig` x `f_dest`.

| Check | Result |
|---|---|
| Join keys, factor product | `faf5_conus_county_od.py` lines 165-185 do exactly this |
| SCTG groups | 01-09, 10-14, 15-19, 20-33, 34-99, as Table 12 |
| Units | FAF `tons` are thousand tons (Table 5); the code multiplies by 1000 |
| Trade types | all three kept (domestic 11.717, import 0.501, export 0.450 billion truck tons), as in the guide's example |
| Conservation | raw FAF mode-1 total 12,667,943,304.9 tons; county OD total 12,667,943,303.053 tons |
| Factors | origin and destination factors sum to 1.000000 for all 132 FAF zones x 5 groups; 3,144 counties |
| Spot check | FAF zone 519 to 519, sctg0109: 12,172,682.0 t x 0.06665 x 0.05311 = 43,090.923 t; the county OD file has 43,090.923436 |
| Trips | 12,667,943,303 / 20 t per truck / 365 = 1,735,334.7 trips per day, matching the OD total |

Deviations (scope and parameters, not errors in the method):

1. **Mode 1 only.** The guide says the truck factors can also be applied to air (mode 4) and multiple modes and mail (mode 5). They carry
   0.008 and 0.627 billion tons, 5.0% of the truck tons, and are not in the OD.
2. **Flat 20 tons per truck** (the build manifest), where `FREIGHT_OD_DISAGGREGATION.md` says the default is the T29 table by SCTG group.
   The BTS guide does not cover payload; this is a ResiFlow choice.

## 2. The FAF5 centroids

The data dictionary: the FAF5 network has "centroid connectors to all U.S. counties, major cargo airports and water ports, and U.S. border
crossings". Link `Class` 50 is "Centroid Connector". A node with `Centroid = 1` is "a county or sub-county centroid"; `CentroidID` is the
"county/sub-county unique identifier". So FAF loads freight at FIPS-numbered centroid nodes that are joined to the road network by Class 50 links.

**The converted network has none of them.** Native `FAF5_Links` has 487,394 links, 3,795 of them Class 50. Our links file has 483,599. By class, the
only difference between the two is exactly the 3,795 Class 50 links. The conversion dropped the centroid connectors, so the loading centroids are not
part of the network the model routes on; the OD builder substituted "nearest road node".

### The 3,796 centroid rows

| Group | Rows | Unique ids | Notes |
|---|---|---|---|
| County centroids, `CentroidID` = county FIPS | 3,400 | 3,142 | 258 ids appear twice as exact duplicate rows (same coordinates, `ID`, `DATA`); 3,133 match TIGER 2022 counties; 9 are pre-2022 ids (8 Connecticut counties 9001-9015, Alaska 2261) |
| Sub-county, id = county FIPS x 1000 + n (n = 1 to 5) | 101 | 101 | e.g. 4013001 (Maricopa), 6073002 (San Diego); every base county also has its own FIPS centroid |
| Sub-county, id 100005-100411 | 295 | about 254 | 41 duplicate rows overall in the non-FIPS group; located in 204 counties; many near borders and ports (ND, ME, WA); their facility type is not populated in the export |
| Total | 3,796 | 3,497 | 299 exact duplicate rows |

All 355 non-FIPS points lie inside a TIGER county, 351 of them in a county that also has its own FIPS centroid. 79 counties hold more than one extra
centroid (Los Angeles 9, Aroostook 7, San Diego 6, Cook 6, Harris 5, Whatcom 5). The dictionary calls them "county or sub-county centroids". The 3,795 connectors exceed the 3,497 unique
centroids, so some centroids have more than one connector.

TIGER 2022 counties with no FIPS centroid: the 11 builder fallbacks (2 Alaska boroughs, 9 Connecticut planning regions) plus the territories, which are out of scope.

### One node per county?

In the OD: 3,144 counties on 3,143 nodes, one node per county, except the Connecticut pair 09120 and 09190 that share one. That is the builder's choice (it keeps one
centroid per county: `normalize_network_centroids` ends with `drop_duplicates("centroid_id")`, and the exact match is on `CentroidID` = county FIPS). It is not a property of the
network, which has up to 9 sub-county centroids in a county. BTS gives county-level factors only, so sub-county splitting needs weights from elsewhere.

## 3. What my earlier fix did, and what it should have been

`scripts/make_conterminous_od.py` re-snapped each county's old OD node to the nearest suitable node of the current (positionally numbered) network and
rewrote the OD node ids. That repairs the geography (99.8% of counties on links of their own state) but **does not give the files the original
FIPS-numbered centroid ids**, it assigns yet another set of positional ids, and it still leaves the centroid connectors missing. It should be treated as an interim repair.

The structural fix: key the OD by the original `CentroidID` (county FIPS), restore the centroid nodes and Class 50 connectors into the network, and bind ids by
a checked crosswalk so a renumbering fails loudly instead of silently scrambling. Not yet built; needs a decision on the points in the main reply.

## 4. Files for review

`Desktop\gis_review\resiflow_od_review.gpkg` now also contains `faf5_loading_centroids` (3,497 unique, with `kind`, `base_county`, `dup_rows`) and
`faf5_centroid_connectors_native` (the 3,795 Class 50 links). Regenerate with `scripts/diagnostics/export_od_review_gpkg.py`.
