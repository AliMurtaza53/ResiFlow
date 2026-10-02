"""Tests for hpms_fclass.py's shared F-class/NHS/tunnel bucketings."""

from __future__ import annotations

import pandas as pd

from resiflow.hpms_fclass import (
    assignment_tier_from_fclass,
    damage_threshold_major_from_fclass,
    derive_hpms_fclass,
    flood_road_class_sophistication,
)


def test_derive_hpms_fclass_prefers_real_value():
    raw = pd.Series([1, 7, None, 10, 5])
    faf5_class = pd.Series([11, 15, 14, 12, 23])
    out = derive_hpms_fclass(raw, faf5_class)
    # 1 and 7 are valid, kept as-is; None and 10 fall back via faf5_class; 5 kept.
    assert out.tolist() == [1, 7, 3, 2, 5]
    assert str(out.dtype) == "Int64"


def test_derive_hpms_fclass_ferry_stays_null():
    raw = pd.Series([None])
    faf5_class = pd.Series([41])
    out = derive_hpms_fclass(raw, faf5_class)
    assert out.isna().all()


def test_assignment_tier_from_fclass():
    fc = pd.Series([1, 2, 3, 4, 5, 6, 7], dtype="Int64")
    tiers = assignment_tier_from_fclass(fc)
    assert tiers.tolist() == [
        "freeway", "freeway", "arterial", "arterial", "collector", "collector", "local_access",
    ]


def test_damage_threshold_major_from_fclass():
    fc = pd.Series([1, 3, 4, 7, None], dtype="Int64")
    major = damage_threshold_major_from_fclass(fc)
    assert major.iloc[0] and major.iloc[1]
    assert not major.iloc[2] and not major.iloc[3]
    assert pd.isna(major.iloc[4])


def test_flood_road_class_sophistication_three_way_split():
    nhs = pd.Series([1, None, 7, 3], index=["a", "b", "c", "d"])
    road_label = pd.Series(["tunnel", "road", "tunnel", "road"], index=["a", "b", "c", "d"])
    out = flood_road_class_sophistication(nhs, road_label)
    assert out["a"] == "sophisticated"  # NHS + tunnel
    assert out["b"] == "ordinary"  # not NHS
    assert out["c"] == "sophisticated"  # NHS + tunnel
    assert out["d"] == "simple"  # NHS, no tunnel


def test_flood_road_class_sophistication_without_tunnel_column():
    nhs = pd.Series([1, None])
    out = flood_road_class_sophistication(nhs, None)
    assert out.tolist() == ["simple", "ordinary"]
