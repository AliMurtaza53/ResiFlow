import pandas as pd
import pytest

import preprocess.build_passenger_subareas as mod


def _fake_crosswalk(state, base=None):
    return pd.DataFrame({"tabblk2020": ["b1", "b2", "b3"], "cty": ["06037", "06037", "99999"]})


def _fake_block_geo(state, base=None):
    return pd.DataFrame(
        {
            "tabblk2020": ["b1", "b2", "b3"],
            "blklondd": [-118.2, -118.3, -70.0],
            "blklatdd": [34.0, 34.1, 40.0],
        }
    )


def _fake_lodes_od(state, job_type="JT00", year=2022, part="main", base=None):
    if part == "aux":
        raise FileNotFoundError
    return pd.DataFrame(
        {
            "h_geocode": ["b1", "b2", "b3"],
            "w_geocode": ["b2", "b1", "b1"],
            "S000": [10.0, 5.0, 3.0],
        }
    )


def test_build_endpoint_blocks_home_restricts_and_weights(monkeypatch):
    monkeypatch.setattr(mod, "read_lodes_crosswalk", _fake_crosswalk)
    monkeypatch.setattr(mod, "read_lodes_od", _fake_lodes_od)
    monkeypatch.setattr(mod, "read_lodes_block_geo", _fake_block_geo)

    blocks = mod.build_endpoint_blocks(["ca"], {"06037"}, "home")

    # b3's home county (99999) is not a target -> excluded
    assert set(blocks["county_fips"]) == {"06037"}
    total_weight = blocks["weight"].sum()
    assert total_weight == pytest.approx(15.0)  # b1 (10) + b2 (5)


def test_build_endpoint_blocks_work_uses_w_geocode(monkeypatch):
    monkeypatch.setattr(mod, "read_lodes_crosswalk", _fake_crosswalk)
    monkeypatch.setattr(mod, "read_lodes_od", _fake_lodes_od)
    monkeypatch.setattr(mod, "read_lodes_block_geo", _fake_block_geo)

    blocks = mod.build_endpoint_blocks(["ca"], {"06037"}, "work")

    # work blocks b2 (from row1, S000=10) and b1 (rows 2+3, S000=5+3=8) are both in 06037
    assert set(blocks["county_fips"]) == {"06037"}
    assert blocks["weight"].sum() == pytest.approx(18.0)


def test_build_endpoint_blocks_rejects_bad_endpoint():
    with pytest.raises(ValueError, match="endpoint must be"):
        mod.build_endpoint_blocks(["ca"], {"06037"}, "both")


def test_assign_blocks_to_nearest_subarea_picks_closest_within_county():
    blocks = pd.DataFrame(
        {
            "tabblk2020": ["b1", "b2"],
            "county_fips": ["06037", "06037"],
            "lon": [-118.2, -118.3],
            "lat": [34.0, 34.1],
        }
    )
    subarea_crosswalk = pd.DataFrame(
        {
            "county_fips": ["06037", "06037"],
            "lon": [-118.2, -118.3],
            "lat": [34.0, 34.1],
            "node_id": ["near_b1", "near_b2"],
        }
    )

    assigned = mod.assign_blocks_to_nearest_subarea(blocks, subarea_crosswalk, "tabblk2020")

    mapping = dict(zip(assigned["tabblk2020"], assigned["node_id"]))
    assert mapping == {"b1": "near_b1", "b2": "near_b2"}


def test_build_intra_county_real_pair_od_preserves_real_pairs(monkeypatch):
    # b1<->b2 live-and-work within 06037 (intra-county); b3's pair crosses
    # into county 99999 and must be excluded.
    monkeypatch.setattr(mod, "read_lodes_crosswalk", _fake_crosswalk)
    monkeypatch.setattr(mod, "read_lodes_od", _fake_lodes_od)
    monkeypatch.setattr(mod, "read_lodes_block_geo", _fake_block_geo)

    home_crosswalk = pd.DataFrame(
        {
            "county_fips": ["06037", "06037"],
            "lon": [-118.2, -118.3],
            "lat": [34.0, 34.1],
            "node_id": ["home_near_b1", "home_near_b2"],
        }
    )
    work_crosswalk = pd.DataFrame(
        {
            "county_fips": ["06037", "06037"],
            "lon": [-118.2, -118.3],
            "lat": [34.0, 34.1],
            "node_id": ["work_near_b1", "work_near_b2"],
        }
    )

    result = mod.build_intra_county_real_pair_od(["ca"], {"06037"}, home_crosswalk, work_crosswalk)

    # row3 (b3->b1, cross-county) is excluded; only rows 1 and 2 (both intra-06037) remain
    assert result["Car21"].sum() == pytest.approx(15.0)
    pairs = dict(zip(zip(result["origin_node"], result["destination_node"]), result["Car21"]))
    assert pairs[("home_near_b1", "work_near_b2")] == pytest.approx(10.0)  # h=b1, w=b2
    assert pairs[("home_near_b2", "work_near_b1")] == pytest.approx(5.0)  # h=b2, w=b1
