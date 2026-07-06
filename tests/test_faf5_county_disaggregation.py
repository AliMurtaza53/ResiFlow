import pandas as pd
import pytest

from resiflow import faf5_county_disaggregation as county


def factor_tables():
    origin = pd.DataFrame(
        [
            {"dms_orig": "101", "origin_county": "01001", "sctgG5": "sctg0109", "f_orig": 0.25},
            {"dms_orig": "101", "origin_county": "01003", "sctgG5": "sctg0109", "f_orig": 0.75},
        ]
    )
    destination = pd.DataFrame(
        [
            {"dms_dest": "201", "destination_county": "02001", "sctgG5": "sctg0109", "f_dest": 0.6},
            {"dms_dest": "201", "destination_county": "02003", "sctgG5": "sctg0109", "f_dest": 0.4},
        ]
    )
    return origin, destination


def regional_od():
    return pd.DataFrame(
        [
            {
                "origin_faf": "101",
                "destination_faf": "201",
                "sctg": "01",
                "mode": "1",
                "year": 2022,
                "tons": 1000.0,
                "value": 50.0,
            }
        ]
    )


def test_factor_sums_by_faf_zone_and_commodity_are_one():
    origin, destination = factor_tables()

    summary = county.validate_disaggregation_factors(origin, destination)

    assert summary["origin_factor_sums"]["within_tolerance"].all()
    assert summary["destination_factor_sums"]["within_tolerance"].all()


def test_disaggregated_totals_match_input_faf_totals_and_preserve_fips_strings():
    origin, destination = factor_tables()
    county_od = county.disaggregate_faf_to_county(regional_od(), origin, destination)
    quality = county.summarize_disaggregation_quality(regional_od().pipe(county.map_faf_sctg_to_sctgG5), county_od)

    assert round(county_od["tons"].sum(), 6) == 1000.0
    assert quality["percent_difference"] == 0.0
    assert set(county_od["origin_county"]) == {"01001", "01003"}


def test_missing_factor_records_are_reported_clearly():
    origin, destination = factor_tables()
    od = regional_od()
    od.loc[0, "origin_faf"] = "999"
    od = county.map_faf_sctg_to_sctgG5(od)

    quality = county.summarize_disaggregation_quality(
        od,
        county.disaggregate_faf_to_county(od, origin, destination),
        origin,
        destination,
    )

    assert quality["missing_origin_factor_records"] == 1
    assert quality["faf_od_records_dropped"] == 1


def test_daily_truck_trips_are_annual_truck_trips_divided_by_365():
    origin, destination = factor_tables()
    county_od = county.disaggregate_faf_to_county(regional_od(), origin, destination)
    trips = county.convert_tons_to_truck_trips(
        county_od,
        pd.DataFrame([{"sctgG5": "sctg0109", "truck_type": "combination", "payload_tons": 10.0}]),
    )

    assert "annual_truck_trips" in trips.columns
    assert trips["daily_truck_trips"].sum() == pytest.approx(trips["annual_truck_trips"].sum() / 365.0)


def test_cli_workflow_writes_county_od_and_summary(tmp_path):
    faf_path = tmp_path / "faf.csv"
    origin_path = tmp_path / "origin.csv"
    destination_path = tmp_path / "destination.csv"
    payload_path = tmp_path / "payload.csv"
    output_path = tmp_path / "county_od.csv"
    summary_path = tmp_path / "summary.json"

    pd.DataFrame(
        [
            {
                "dms_orig": "101",
                "dms_dest": "201",
                "dms_mode": "1",
                "sctg2": "01",
                "tons_2022": "1.0",
                "value_2022": "5.0",
            }
        ]
    ).to_csv(faf_path, index=False)
    origin, destination = factor_tables()
    origin.rename(columns={"origin_county": "dms_orig_cnty"}).to_csv(origin_path, index=False)
    destination.rename(columns={"destination_county": "dms_dest_cnty"}).to_csv(destination_path, index=False)
    pd.DataFrame([{"sctgG5": "sctg0109", "truck_type": "combination", "payload_tons": "20"}]).to_csv(
        payload_path,
        index=False,
    )

    exit_code = county.main(
        [
            "--faf-od",
            str(faf_path),
            "--origin-factors",
            str(origin_path),
            "--destination-factors",
            str(destination_path),
            "--output",
            str(output_path),
            "--year",
            "2022",
            "--mode",
            "truck",
            "--payload-factors",
            str(payload_path),
            "--summary-json",
            str(summary_path),
            "--read-chunksize",
            "2",
            "--faf-zone-filter",
            "101",
        ]
    )

    assert exit_code == 0
    assert output_path.exists()
    assert summary_path.exists()
    assert pd.read_csv(output_path, dtype=str)["origin_county"].str.startswith("010").all()


def test_load_faf_regional_od_streams_and_filters_csv(tmp_path):
    faf_path = tmp_path / "faf.csv"
    pd.DataFrame(
        [
            {"dms_orig": "101", "dms_dest": "201", "dms_mode": "1", "sctg2": "01", "tons_2022": "1"},
            {"dms_orig": "301", "dms_dest": "401", "dms_mode": "1", "sctg2": "01", "tons_2022": "9"},
        ]
    ).to_csv(faf_path, index=False)

    loaded = county.load_faf_regional_od(
        faf_path,
        year=2022,
        mode="truck",
        faf_zone_filter=["101"],
        chunksize=1,
    )

    assert len(loaded) == 1
    assert loaded.loc[0, "origin_faf"] == "101"


def test_loader_pads_numeric_county_fips_without_casting(tmp_path):
    origin_path = tmp_path / "origin.csv"
    destination_path = tmp_path / "destination.csv"
    pd.DataFrame(
        [{"dms_orig": "101", "dms_orig_cnty": "1073", "sctgG5": "sctg0109", "f_orig": "1"}]
    ).to_csv(origin_path, index=False)
    pd.DataFrame(
        [{"dms_dest": "201", "dms_dest_cnty": "10003", "sctgG5": "sctg0109", "f_dest": "1"}]
    ).to_csv(destination_path, index=False)

    origin, destination = county.load_truck_disaggregation_factors(origin_path, destination_path)

    assert origin.loc[0, "origin_county"] == "01073"
    assert destination.loc[0, "destination_county"] == "10003"


def test_faf_zone_ids_normalize_for_factor_joins():
    origin, destination = factor_tables()
    od = regional_od()
    od.loc[0, "origin_faf"] = "0101"
    od.loc[0, "destination_faf"] = "0201"

    county_od = county.disaggregate_faf_to_county(od, origin, destination)

    assert round(county_od["tons"].sum(), 6) == 1000.0
    assert set(county_od["origin_faf"]) == {"101"}
