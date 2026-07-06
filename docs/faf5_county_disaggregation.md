# FAF5 County Disaggregation With BTS Experimental Factors

## Purpose

This preprocessing step converts FAF5 regional truck OD flows into county-to-county freight OD rows using the BTS experimental county-level FAF truck disaggregation factors. It is a transparent public approximation of the FAF5 freight preprocessing workflow and does not attempt to reproduce FHWA's internal TransCAD network assignment model.

The NIRD network assignment logic is unchanged. This module only creates a county-level OD table that can be mapped to network nodes later.

## Inputs

Required:

- FAF regional OD table with FAF origin, FAF destination, commodity, mode, annual tons, and optionally value.
- BTS truck origin factor CSV, for example `All_Experimental_Disaggregation_Factors/truck_origin_factors.csv`.
- BTS truck destination factor CSV, for example `All_Experimental_Disaggregation_Factors/truck_destination_factors.csv`.

Current local raw data layout:

```text
C:\Users\alimu\NIRD_Data\faf5_data\
├── regional_od_data\FAF5.7.1_2018-2024.csv
├── network_data\FAF5Network.gdb
├── regions_shp\Freight_Analysis_Framework_(FAF5)_Regions.shp
└── county_disaggregation_factors\
    ├── truck_origin_factors.csv
    └── truck_destination_factors.csv
```

Optional:

- Payload factor table with `sctgG5`, `truck_type`, and `payload_tons`.
- County-to-network-node map with `county_id,node_id` if the county OD should be converted to Script 1 assignment OD later.

The factor loader accepts these county column variants:

- Origin county: `dms_orig_c`, `dms_orig_cnty`, or `origin_county`
- Destination county: `dms_dest_c`, `dms_dest_cnty`, or `destination_county`

County identifiers are always read as strings. Purely numeric county identifiers shorter than five characters are left-padded to standard five-character FIPS form.

## Method

For each FAF OD record:

1. Map the FAF commodity to a BTS `sctgG5` group.
2. Select origin county factors matching `dms_orig` and `sctgG5`.
3. Select destination county factors matching `dms_dest` and `sctgG5`.
4. Cross join the origin and destination county factors.
5. Compute:

```text
county_tons = faf_tons * f_orig * f_dest
county_value = faf_value * f_orig * f_dest
```

If payload factors are supplied:

```text
annual_truck_trips = county_tons / payload_tons
daily_truck_trips = annual_truck_trips / 365
```

## CLI

Use the compatibility module from the repo root:

```powershell
python -m src.preprocess.faf5_county_disaggregation ^
  --faf-od path\to\faf_regional_od.csv ^
  --origin-factors All_Experimental_Disaggregation_Factors\truck_origin_factors.csv ^
  --destination-factors All_Experimental_Disaggregation_Factors\truck_destination_factors.csv ^
  --output data\processed\faf5_county_truck_od.csv ^
  --year 2022 ^
  --mode truck ^
  --read-chunksize 200000 ^
  --faf-zone-filter 511,512,513,519
```

The reusable implementation is `nird.faf5_county_disaggregation`, so this also works:

```powershell
$env:PYTHONPATH = "src"
python -m nird.faf5_county_disaggregation --help
```

With `PYTHONPATH=src`, the shorter wrapper also works:

```powershell
$env:PYTHONPATH = "src"
python -m preprocess.faf5_county_disaggregation --help
```

## Output Schema

The county OD output contains:

- `origin_faf`
- `destination_faf`
- `origin_county`
- `destination_county`
- `sctgG5`
- `mode`
- `year`
- `tons`
- `value`
- `annual_truck_trips`, if payload factors are supplied
- `daily_truck_trips`, if payload factors are supplied

## Validation

The module reports:

- total FAF tons before disaggregation
- total county tons after disaggregation
- percent difference
- missing origin factor records
- missing destination factor records
- FAF OD records dropped because factors were unavailable
- number of output county-to-county OD records

Factor sums by FAF zone and commodity are also unit tested. For national runs, small floating-point differences around 1.0 are expected.

## Integration Point

`scripts/run_va_workflow.py` keeps synthetic inverse-distance OD as the default:

```powershell
python scripts\run_va_workflow.py
```

To use a county experimental OD output, pass:

```powershell
python scripts\run_va_workflow.py ^
  --od-source faf5_county_experimental ^
  --county-od-path data\processed\faf5_county_truck_od.csv ^
  --county-node-map data\processed\county_node_map.csv
```

The county node map must contain `county_id,node_id`. If the county OD file already has `origin_node`, `destination_node`, and `Car21`, the node map is not required.

## Limitations

- The BTS factors are experimental and public; they should be treated as an approximation.
- County OD is not assignment-ready until counties are mapped to network nodes.
- The first implementation chunks by FAF OD rows and is intended to work first for Virginia or filtered regional subsets before scaling to CONUS.
- For Virginia tests from the national FAF CSV, use `--faf-zone-filter 511,512,513,519`; these are the Virginia FAF zones observed in the FAF5 network node centroids.

The first VA-filtered 2022 run wrote:

```text
C:\Users\alimu\NIRD_Data\faf5_data\processed\faf5_county_truck_od_va_2022.parquet
C:\Users\alimu\NIRD_Data\faf5_data\processed\faf5_county_truck_od_va_2022_summary.json
```

It preserves FAF tonnage within floating-point tolerance and currently includes all OD rows where either origin or destination FAF zone is in the Virginia set.
