# LODES passenger OD module

County-to-county passenger demand from Census LEHD LODES8, designed to plug into the
existing NIRD network assignment workflow alongside freight (FAF5).

## Data sources

- LODES8 base URL: https://lehd.ces.census.gov/data/lodes/LODES8/
- LEHD code samples: https://lehd.ces.census.gov/data/lehd-code-samples/sections/lodes/basic_examples.html

## Scope (v1)

- **County-to-county** home-to-work flows only (block OD aggregated with the official geographic crosswalk).
- **Inner-county trips** are included in the county matrix (`origin_county == destination_county`); within-county disaggregation is deferred.
- **Job counts (`S000`)** are used as a daily person-trip proxy for `vehicle_type=car` assignment.

## Files

| File | Role |
|------|------|
| `src/nird/lodes_paths.py` | LODES URL/path helpers, CONUS state list |
| `src/nird/lodes_county_od.py` | Read OD + crosswalk, aggregate to county pairs |
| `scripts/build_lodes_passenger_od.py` | CLI: county OD + optional network mapping |
| `tests/test_lodes_county_od.py` | Unit tests (no network download) |

## Build county OD (single state smoke)

```powershell
python scripts/build_lodes_passenger_od.py --states va --year 2022 --skip-centroid
```

## Build county OD + map to network nodes

```powershell
python scripts/build_lodes_passenger_od.py --states va md dc --year 2022 --force-county
```

Outputs under `lodes_data/processed/` (or `NIRD_LODES_DATA_ROOT/processed/`):

- `lodes_county_od_jt00_2022.parquet`
- `lodes_passenger_centroid_od_jt00_2022.parquet`
- `lodes_passenger_assignment_od_jt00_2022.parquet` (`origin_node`, `destination_node`, `Car21`)

## Environment

| Variable | Purpose |
|----------|---------|
| `NIRD_LODES_DATA_ROOT` | Local mirror of LODES8 files (recommended for CONUS builds) |
| `NIRD_LODES8_BASE_URL` | Override download base URL |
| `NIRD_PASSENGER_OD_PATH` | Passenger assignment parquet for Script 1 / Script 4 |
| `NIRD_ENABLE_PASSENGER_REROUTING` | Set to `1` to run passenger rerouting in Script 4 |

## Full passenger + freight workflow

```powershell
# Build LODES county OD + network mapping, then Pass A/B with combined OD
powershell -File scripts/run_passenger_freight_conus.ps1 -MaxFlowIterations 0

# Or use Patch 5 directly once assignment OD exists
powershell -File scripts/run_patch5_recovery_conus.ps1 -IncludePassenger -MaxFlowIterations 0
```

Script 1 merges freight FAF5 OD with passenger `Car21` when `NIRD_PASSENGER_OD_PATH` is set.
Script 4 writes `cost_matrix_passenger_by_scenario.csv` alongside freight `cost_matrix_by_scenario.csv`.

Missing LODES files are downloaded on demand into `data/lodes_data/{state}/` when no local mirror is populated.
- Hazard/rerouting coupling for passenger mode in Script 4.
