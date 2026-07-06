import pandas as pd

from resiflow import faf5_conus_county_od as conus


def test_aggregate_faf_chunk_to_county_sctg_preserves_commodity():
    faf = pd.DataFrame(
        [
            {
                "origin_faf": "101",
                "destination_faf": "201",
                "sctg": "01",
                "sctgG5": "sctg0109",
                "mode": "1",
                "year": 2022,
                "tons": 100.0,
                "value": 50.0,
            },
            {
                "origin_faf": "101",
                "destination_faf": "201",
                "sctg": "20",
                "sctgG5": "sctg2033",
                "mode": "1",
                "year": 2022,
                "tons": 200.0,
                "value": 70.0,
            },
        ]
    )
    origin = pd.DataFrame(
        [
            {"dms_orig": "101", "origin_county": "01001", "sctgG5": "sctg0109", "f_orig": 1.0},
            {"dms_orig": "101", "origin_county": "01001", "sctgG5": "sctg2033", "f_orig": 1.0},
        ]
    )
    destination = pd.DataFrame(
        [
            {"dms_dest": "201", "destination_county": "02001", "sctgG5": "sctg0109", "f_dest": 1.0},
            {"dms_dest": "201", "destination_county": "02001", "sctgG5": "sctg2033", "f_dest": 1.0},
        ]
    )

    detail = conus.aggregate_faf_chunk_to_county_sctg(faf, origin, destination, od_chunk_size=1)

    assert set(detail["sctgG5"]) == {"sctg0109", "sctg2033"}
    assert detail.loc[detail["sctgG5"] == "sctg0109", "tons"].iloc[0] == 100.0
    assert detail.loc[detail["sctgG5"] == "sctg2033", "tons"].iloc[0] == 200.0


def test_aggregates_faf_rows_directly_to_total_county_pairs():
    faf = pd.DataFrame(
        [
            {
                "origin_faf": "101",
                "destination_faf": "201",
                "sctg": "01",
                "sctgG5": "sctg0109",
                "mode": "1",
                "year": 2022,
                "tons": 100.0,
                "value": 50.0,
            },
            {
                "origin_faf": "101",
                "destination_faf": "201",
                "sctg": "02",
                "sctgG5": "sctg0109",
                "mode": "1",
                "year": 2022,
                "tons": 200.0,
                "value": 70.0,
            },
        ]
    )
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

    total = conus.aggregate_faf_chunk_to_county_pairs(faf, origin, destination, od_chunk_size=1)

    assert len(total) == 4
    assert total["tons"].sum() == 300.0
    assert total["value"].sum() == 120.0
    assert set(total.columns) == {"origin_county", "destination_county", "tons", "value"}
