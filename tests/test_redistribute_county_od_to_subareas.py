import pandas as pd
import pytest

from preprocess.redistribute_county_od_to_subareas import (
    build_full_crosswalk,
    redistribute,
    replace_intra_county_pairs,
)


def test_build_full_crosswalk_merges_multinode_and_existing():
    multinode = pd.DataFrame(
        {
            "county_fips": ["00001", "00001"],
            "node_id": ["n1", "n2"],
            "weight": [0.6, 0.4],
        }
    )
    existing = pd.DataFrame(
        {
            "county_id": ["00001", "00002"],
            "node_id": ["n_old_unused", "n3"],
        }
    )

    full = build_full_crosswalk(multinode, existing)

    assert set(full.loc[full["county_fips"] == "00001", "node_id"]) == {"n1", "n2"}
    assert set(full.loc[full["county_fips"] == "00002", "node_id"]) == {"n3"}
    weight_sums = full.groupby("county_fips")["weight"].sum()
    assert weight_sums.loc["00001"] == pytest.approx(1.0)
    assert weight_sums.loc["00002"] == pytest.approx(1.0)


def test_build_full_crosswalk_rejects_bad_weights():
    multinode = pd.DataFrame({"county_fips": ["00001"], "node_id": ["n1"], "weight": [0.5]})
    existing = pd.DataFrame({"county_id": [], "node_id": []})

    with pytest.raises(ValueError, match="do not sum to 1.0"):
        build_full_crosswalk(multinode, existing)


def test_redistribute_preserves_total_demand_and_splits_by_weight():
    county_od = pd.DataFrame(
        {
            "origin_county": ["A", "A"],
            "destination_county": ["B", "C"],
            "Car21": [100.0, 50.0],
        }
    )
    full_crosswalk = pd.DataFrame(
        {
            "county_fips": ["A", "A", "B", "C"],
            "node_id": ["a1", "a2", "b1", "c1"],
            "weight": [0.7, 0.3, 1.0, 1.0],
        }
    )

    result = redistribute(county_od, full_crosswalk)

    assert result["Car21"].sum() == pytest.approx(150.0)
    a1_to_b1 = result.loc[(result["origin_node"] == "a1") & (result["destination_node"] == "b1"), "Car21"].iloc[0]
    a2_to_b1 = result.loc[(result["origin_node"] == "a2") & (result["destination_node"] == "b1"), "Car21"].iloc[0]
    assert a1_to_b1 == pytest.approx(70.0)
    assert a2_to_b1 == pytest.approx(30.0)
    # single-node destination row for C keeps the full origin split, demand unchanged in total
    c_total = result.loc[result["destination_node"] == "c1", "Car21"].sum()
    assert c_total == pytest.approx(50.0)


def test_redistribute_with_asymmetric_origin_destination_crosswalks():
    # Passenger demand: county A's home-weighted origin split differs from
    # its work-weighted destination split.
    county_od = pd.DataFrame({"origin_county": ["A"], "destination_county": ["A"], "Car21": [100.0]})
    home_crosswalk = pd.DataFrame({"county_fips": ["A", "A"], "node_id": ["home1", "home2"], "weight": [0.8, 0.2]})
    work_crosswalk = pd.DataFrame({"county_fips": ["A", "A"], "node_id": ["work1", "work2"], "weight": [0.3, 0.7]})

    result = redistribute(county_od, home_crosswalk, destination_crosswalk=work_crosswalk)

    assert result["Car21"].sum() == pytest.approx(100.0)
    home1_work1 = result.loc[(result["origin_node"] == "home1") & (result["destination_node"] == "work1"), "Car21"].iloc[0]
    assert home1_work1 == pytest.approx(0.8 * 0.3 * 100.0)


def test_redistribute_raises_if_demand_not_preserved():
    county_od = pd.DataFrame({"origin_county": ["A"], "destination_county": ["B"], "Car21": [100.0]})
    # destination county "B" missing from crosswalk -> inner merge drops the row
    full_crosswalk = pd.DataFrame({"county_fips": ["A"], "node_id": ["a1"], "weight": [1.0]})

    with pytest.raises(ValueError, match="Demand total not preserved"):
        redistribute(county_od, full_crosswalk)


def test_replace_intra_county_pairs_swaps_diagonal_and_rescales_exactly():
    # County A's own diagonal (home==work==A) totals 100 at the county
    # level; the real block-pair breakdown sums to only 90 (a plausible
    # LODES-read discrepancy) and must be rescaled to match exactly.
    county_od = pd.DataFrame(
        {
            "origin_county": ["A", "A"],
            "destination_county": ["A", "B"],
            "Car21": [100.0, 20.0],
        }
    )
    real_intra_county_od = pd.DataFrame(
        {
            "origin_node": ["home1", "home2"],
            "destination_node": ["work1", "work2"],
            "Car21": [60.0, 30.0],
        }
    )
    home_crosswalk = pd.DataFrame({"node_id": ["home1", "home2"], "county_fips": ["A", "A"]})
    work_crosswalk = pd.DataFrame({"node_id": ["work1", "work2"], "county_fips": ["A", "A"]})

    remaining_county_od, rescaled = replace_intra_county_pairs(
        county_od, real_intra_county_od, home_crosswalk, work_crosswalk
    )

    # the A->A diagonal row is gone; the A->B row is untouched
    assert len(remaining_county_od) == 1
    assert remaining_county_od.iloc[0]["destination_county"] == "B"

    # rescaled real pairs now sum to EXACTLY the original diagonal total (100), not 90
    assert rescaled["Car21"].sum() == pytest.approx(100.0)
    assert rescaled.set_index(["origin_node", "destination_node"]).loc[("home1", "work1"), "Car21"] == pytest.approx(
        60.0 * 100.0 / 90.0
    )


def test_replace_intra_county_pairs_raises_if_target_county_has_no_real_pairs():
    county_od = pd.DataFrame({"origin_county": ["A"], "destination_county": ["A"], "Car21": [100.0]})
    real_intra_county_od = pd.DataFrame({"origin_node": ["home1"], "destination_node": ["work1"], "Car21": [50.0]})
    # crosswalk maps the real pair's nodes to county B, not A -- A has no real pairs at all
    home_crosswalk = pd.DataFrame({"node_id": ["home1"], "county_fips": ["B"]})
    work_crosswalk = pd.DataFrame({"node_id": ["work1"], "county_fips": ["B"]})

    with pytest.raises(ValueError, match="No real intra-county pairs"):
        replace_intra_county_pairs(
            county_od, real_intra_county_od, home_crosswalk, work_crosswalk, target_counties={"A"}
        )
