# FAF5 Freight OD Disaggregation Integration

## Where It Fits

The freight OD disaggregation module belongs in the preprocessing stage, after the FAF5 road network has been converted/clipped and before Script 1 reads its OD parquet.

Current pipeline:

```text
FAF5 network/centroids
  -> scripts/run_va_workflow.py or convert_faf5_to_nird.py
  -> inputs/networks/faf5/faf5_road_links.gpq
  -> inputs/census_datasets/faf5_od_matrix.pq
  -> scripts/1_network_flow_model_revision.py
```

New freight path:

```text
FAF5 commodity flows + FAF zone/subarea inputs
  -> nird.freight_od_disaggregation
  -> county/subcounty commodity tonnage OD
  -> county/subcounty truck trip OD
  -> assignment-ready OD: origin_node, destination_node, Car21
  -> inputs/census_datasets/faf5_od_matrix.pq
  -> scripts/1_network_flow_model_revision.py
```

Script 1 and `nird.road_revised.network_flow_model` are not changed. The new module only prepares the OD table that Script 1 already consumes.

## Integration Hooks

`scripts/run_va_workflow.py` now keeps the existing synthetic inverse-distance OD as the default. If all freight input paths are supplied, it runs the freight disaggregation path and writes the freight assignment OD into the same Script 1 handoff location:

```powershell
python scripts\run_va_workflow.py `
  --freight-flow-table path\to\faf5_flows.csv `
  --freight-crosswalk path\to\faf_zone_subarea_crosswalk.csv `
  --freight-weights path\to\subarea_weights.csv `
  --freight-centroids path\to\subarea_centroids.parquet `
  --freight-payloads path\to\payload_factors.csv `
  --freight-year 2021
```

Optional:

```powershell
  --freight-distance-matrix path\to\subarea_skim.parquet `
  --freight-mode-filter 1 `
  --freight-tons-unit thousand_tons
```

## Full-USA County OD Matrix

For the current local FAF5 layout, read the OD file from `regional_od_data` and
the truck county factors from `county_disaggregation_factors`. The CONUS runner
streams directly to a total county-to-county matrix and does not use the
IX/XI/XX/II treatment for smaller state or regional models:

```powershell
python -m nird.faf5_conus_county_od `
  --year 2022 `
  --mode truck
```

By default this uses:

| Input/output | Path |
|---|---|
| FAF5 OD | `C:\Users\alimu\NIRD_Data\faf5_data\regional_od_data\FAF5.7.1_2018-2024.csv` |
| Origin county factors | `C:\Users\alimu\NIRD_Data\faf5_data\county_disaggregation_factors\truck_origin_factors.csv` |
| Destination county factors | `C:\Users\alimu\NIRD_Data\faf5_data\county_disaggregation_factors\truck_destination_factors.csv` |
| Output matrix | `C:\Users\alimu\NIRD_Data\faf5_data\processed\faf5_county_truck_od_usa_2022_total.parquet` |
| Summary | `C:\Users\alimu\NIRD_Data\faf5_data\processed\faf5_county_truck_od_usa_2022_total_summary.json` |

## Required Schemas

### FAF Flow Input

Required normalized columns are `origin_faf_zone`, `destination_faf_zone`, `commodity`, `mode`, `tons`, `value`, and `year`.

FAF CSV aliases are accepted by `normalize_faf_flows`: `dms_orig`, `dms_dest`, `sctg2`, `dms_mode`, `tons_YYYY`, and `value_YYYY`.

### FAF Zone To Subarea Crosswalk

| Column | Meaning |
|---|---|
| `faf_zone` | Parent FAF zone code |
| `subarea_id` | County, subcounty, port, airport, or border-crossing unit |

### Production/Attraction Weights

| Column | Meaning |
|---|---|
| `subarea_id` | Disaggregated geography ID |
| `commodity` | SCTG/commodity group or `all` fallback |
| `production_weight` | Non-negative origin weight |
| `attraction_weight` | Non-negative destination weight |

### Subarea Centroids / Node Map

| Column | Meaning |
|---|---|
| `subarea_id` | Disaggregated geography ID |
| `node_id` | Optional direct assignment-node mapping |
| `geometry` or `x`/`y` | Used to nearest-map to road nodes when `node_id` is not provided |

### Payload Factors

| Column | Meaning |
|---|---|
| `commodity` | SCTG/commodity group or `all` fallback |
| `truck_type` | Truck type label |
| `payload_tons` | Average tons per truck |
| `distance_bin` | Optional placeholder for haul-distance-specific payloads |

### Optional Distance Matrix

| Column | Meaning |
|---|---|
| `origin_subarea_id` | Origin subarea |
| `destination_subarea_id` | Destination subarea |
| `distance` | Skim distance used by the gravity impedance term |

## Outputs

The module writes:

| Output | Columns |
|---|---|
| Disaggregated tonnage OD | `origin_faf_zone`, `destination_faf_zone`, `origin_subarea_id`, `destination_subarea_id`, `commodity`, `mode`, `tons`, `value`, `year` |
| Truck trip OD | Tonnage OD columns plus `truck_type`, `payload_tons`, `truck_trips_annual`, `truck_trips_daily` |
| Assignment OD | `origin_node`, `destination_node`, `Car21` |
| Diagnostics | FAF total preservation by FAF OD/commodity/mode/year |

The assignment OD is the only table Script 1 needs.
