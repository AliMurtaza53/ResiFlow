# FAF5.7.1 against FAF6.0 (documented; decision: stay on FAF5 for now)

Written 2026-11-11. FAF6.0 downloaded from https://faf.ornl.gov/faf6/data/Download_Files/ZIP/FAF6.0.zip into `Desktop\data\faf6_data\` (FAF6.0.csv 76 MB, FAF6_Metadata.xlsx).
Both files compared directly on 2022 flows.

## Data

| | FAF5.7.1 | FAF6.0 |
|---|---|---|
| Columns | 56 (years 2017-2024, forecasts, `dist_band`) | 11 (`tons_2022`, `value_2022` only) |
| Domestic zones | 132 | 134 |
| Zone changes | | Iowa (190) split into 191 Des Moines-Ames-West Des Moines and 199 Remainder of Iowa; 395 Toledo-Findlay-Tiffin carved out of 399 Remainder of Ohio |
| Rows | 2,671,386 | 1,921,887 |
| Truck rows with tons in 2022 | 684,470 | 732,981 |
| 2022 truck tons, billions | 12.668 (domestic 11.717, import 0.501, export 0.450) | 12.201 (domestic 11.244, import 0.508, export 0.449) |
| 2022 rail / water / air / multiple modes and mail / pipeline, billions | 1.566 / 0.777 / 0.008 / 0.627 / 3.982 | 1.828 / 0.540 / 0.009 / 1.108 / 3.736 |
| All modes, billions | 19.827 | 19.633 |

Truck tons by origin zone, FAF6 over FAF5: median 0.92, 5th to 95th percentile 0.63 to 1.64.

## Vintage

BTS states FAF6 is built on 2022 data and the 2022 Commodity Flow Survey, with a zone system consistent with the 2022 survey (BTS FAF newsroom release of 2026-07-31,
https://www.bts.gov/newsroom/freight-analysis-framework-new-benchmark-release-7312026). FAF5 was built on 2017 data; its 2022 values are updated estimates.
On vintage FAF6 is the better source.

## Why it is not a drop-in replacement

- The BTS county disaggregation factors cover the 132 FAF5 zones (BTS says the county product is based on FAF5.6.1; I found no FAF6 factors, but could not read the BTS pages
  directly: they return HTTP 403 to automated requests, so this rests on search results).
- Zones 191, 199 and 395 have no factors, and the zones they were cut from (190, 399) have factors for the old boundaries.
- To use FAF6 we would assign counties to the new zones from the Census delineation files and renormalize the BTS factors, then check against FAF6 zone totals.

## Decision (2026-11-11)

Document FAF6 and keep the baseline on FAF5. Revisit once county factors for the 134 zones exist or we build them.
