import pandas as pd

from resiflow import lodes_county_od as lodes


def test_normalize_county_fips():
    assert lodes.normalize_county_fips("34001") == "34001"
    assert lodes.normalize_county_fips(51059.0) == "51059"
    assert lodes.normalize_county_fips("51059") == "51059"


def test_aggregate_od_to_county_sums_jobs_by_county_pair():
    od = pd.DataFrame(
        [
            {"w_geocode": "510590001001001", "h_geocode": "510130001001001", "S000": 10},
            {"w_geocode": "510590001001002", "h_geocode": "510130001001002", "S000": 5},
            {"w_geocode": "510590001001003", "h_geocode": "510590001001003", "S000": 3},
        ]
    )
    lookup = pd.DataFrame(
        [
            {"tabblk2020": "510130001001001", "cty": "51013"},
            {"tabblk2020": "510130001001002", "cty": "51013"},
            {"tabblk2020": "510590001001001", "cty": "51059"},
            {"tabblk2020": "510590001001002", "cty": "51059"},
            {"tabblk2020": "510590001001003", "cty": "51059"},
        ]
    )

    county_od = lodes.aggregate_od_to_county(od, lookup, year=2022, job_type="JT00")

    assert set(county_od.columns) >= {"origin_county", "destination_county", "jobs"}
    pair = county_od.set_index(["origin_county", "destination_county"]).loc[("51013", "51059"), "jobs"]
    assert pair == 15.0
    intra = county_od.set_index(["origin_county", "destination_county"]).loc[("51059", "51059"), "jobs"]
    assert intra == 3.0


def test_build_state_county_od_combines_main_and_aux():
    calls: list[str] = []

    def fake_read_od(state, *, job_type, year, part, base=None):
        calls.append(part)
        if part == "main":
            return pd.DataFrame(
                [{"w_geocode": "510590001001001", "h_geocode": "510590001001002", "S000": 4}]
            )
        return pd.DataFrame(
            [{"w_geocode": "510590001001001", "h_geocode": "240310001001001", "S000": 6}]
        )

    lookup = pd.DataFrame(
        [
            {"tabblk2020": "510590001001001", "cty": "51059"},
            {"tabblk2020": "510590001001002", "cty": "51059"},
            {"tabblk2020": "240310001001001", "cty": "24031"},
        ]
    )

    original = lodes.read_lodes_od
    lodes.read_lodes_od = fake_read_od
    try:
        county_od = lodes.build_state_county_od(
            "va",
            year=2022,
            block_county_lookup=lookup,
        )
    finally:
        lodes.read_lodes_od = original

    assert calls == ["main", "aux"]
    assert county_od["jobs"].sum() == 10.0
    assert set(county_od["origin_county"]) == {"51059", "24031"}


def test_county_od_to_assignment_schema_sets_car_flows():
    county_od = pd.DataFrame(
        [
            {"origin_county": "51013", "destination_county": "51059", "jobs": 12.0, "year": 2022},
        ]
    )
    mapped = lodes.county_od_to_assignment_schema(county_od)
    assert mapped.loc[0, "origin_detail_zone"] == "51013"
    assert mapped.loc[0, "destination_detail_zone"] == "51059"
    assert mapped.loc[0, "daily_truck_trips"] == 12.0
    assert mapped.loc[0, "mode"] == "car"
