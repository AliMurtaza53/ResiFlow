"""Tests for scripts/download_nbi_bridges.py's coordinate decoding and
scripts/build_nbi_bridge_index.py's spatial join.

Coordinate test values are taken from real downloaded NBI records (2026-08-17):
Wilmington, DE structure '1001 279' and Guam structure '66180000000G042' --
not synthetic, to keep the DMS decode honest against the real encoding.
"""

from __future__ import annotations

import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from download_nbi_bridges import (  # noqa: E402
    _nbi_dms_to_decimal,
    _clean_deck_width,
    ROUTE_PREFIX_LABELS,
    SERVICE_LEVEL_LABELS,
    FUNCTIONAL_CLASS_LABELS,
)
from build_nbi_bridge_index import build_bridge_index  # noqa: E402


def test_label_mappings_match_authoritative_coding_guide():
    # FHWA "Recording and Coding Guide", reached via the data dictionary DOI
    # (https://doi.org/10.21949/1519105 -> bridge/mtguide.pdf), Items 5B/5C/26
    # (pages 14, 14, 24). Locks in the corrected mappings against regression
    # -- an earlier version of this dict guessed SERVICE_LEVEL_005C's codes
    # from memory and got code 7 wrong (guessed "frontage road", it's
    # actually "Ramp, Wye, Connector, etc.").
    assert ROUTE_PREFIX_LABELS["4"] == "County highway"
    assert "5" not in ROUTE_PREFIX_LABELS or "unnumbered" not in ROUTE_PREFIX_LABELS.get("5", "")
    assert SERVICE_LEVEL_LABELS["7"] == "Ramp, Wye, Connector, etc."
    assert "5" not in SERVICE_LEVEL_LABELS  # code 5 does not exist in the real scheme
    assert FUNCTIONAL_CLASS_LABELS["02"] == "Rural - Principal Arterial - Other"
    assert FUNCTIONAL_CLASS_LABELS["12"] == "Urban - Principal Arterial - Other Freeway/Expressway"


def test_decode_real_delaware_latitude():
    # Wilmington, DE structure 1001 279.
    assert _nbi_dms_to_decimal("39460947", digits_before_seconds=4) == pytest.approx(
        39.7692, abs=1e-4
    )


def test_decode_real_delaware_longitude_magnitude():
    # Longitude is decoded unsigned here; sign is applied by the caller.
    assert _nbi_dms_to_decimal("075343612", digits_before_seconds=5) == pytest.approx(
        75.5767, abs=1e-4
    )


def test_decode_real_guam_coordinates():
    # Guam structure 66180000000G042 -- eastern hemisphere, no negation.
    assert _nbi_dms_to_decimal("13233571", digits_before_seconds=4) == pytest.approx(
        13.3932, abs=1e-4
    )
    assert _nbi_dms_to_decimal("144453839", digits_before_seconds=5) == pytest.approx(
        144.76066, abs=1e-4
    )


def test_decode_rejects_invalid_minutes():
    # Real malformed DE record: structure 1266B347's LAT_016='03943500'
    # decodes to minutes=94, which cannot be a real minutes value.
    assert _nbi_dms_to_decimal("03943500", digits_before_seconds=4) is None


def test_decode_blank_and_zero_are_unrecorded():
    assert _nbi_dms_to_decimal("", digits_before_seconds=4) is None
    assert _nbi_dms_to_decimal("00000000", digits_before_seconds=4) is None


def test_deck_width_zero_is_treated_as_missing():
    # 0 is NBI's "not recorded" convention (confirmed: 14.3% of real
    # national structures carry exactly 0), not a genuine zero-width bridge.
    cleaned = _clean_deck_width(pd.Series(["0", "0.0", "12.5", "", "8.2"]))
    assert cleaned.isna().tolist() == [True, True, False, True, False]
    assert cleaned.dropna().tolist() == pytest.approx([12.5, 8.2])


def _toy_links_and_nbi(tmp_path):
    # Two links sharing identical geometry (a bidirectional pair, matching
    # confirmed real FAF5-derived network behavior) plus one isolated link.
    links = gpd.GeoDataFrame(
        {"e_id": ["a_fwd", "a_rev", "b"]},
        geometry=[
            LineString([(0, 0), (1000, 0)]),
            LineString([(1000, 0), (0, 0)]),
            LineString([(0, 5000), (1000, 5000)]),
        ],
        crs="EPSG:9311",
    )
    links_path = tmp_path / "links.gpq"
    links.to_parquet(links_path)

    mid_a = gpd.GeoSeries([LineString([(0, 0), (1000, 0)]).interpolate(0.5, normalized=True)], crs="EPSG:9311").to_crs("EPSG:4326").iloc[0]
    mid_b = gpd.GeoSeries([LineString([(0, 5000), (1000, 5000)]).interpolate(0.5, normalized=True)], crs="EPSG:9311").to_crs("EPSG:4326").iloc[0]

    nbi = pd.DataFrame(
        {
            "structure_number": ["S1", "S2", "S3", "S_FAR"],
            "latitude": [mid_a.y, mid_a.y, mid_b.y, 0.0],
            "longitude": [mid_a.x, mid_a.x, mid_b.x, 0.0],
            "deck_width_m": [10.0, 20.0, 15.0, 5.0],
            "structure_length_m": [30.0, 40.0, 50.0, 10.0],
        }
    )
    nbi_path = tmp_path / "nbi.parquet"
    nbi.to_parquet(nbi_path)
    return nbi_path, links_path


def test_join_matches_within_distance_and_rejects_far_structure(tmp_path):
    nbi_path, links_path = _toy_links_and_nbi(tmp_path)
    index, stats = build_bridge_index(nbi_path, links_path, max_distance_m=100.0)

    assert stats["total_structures"] == 4
    assert stats["matched_structures"] == 3
    assert stats["unmatched_structures"] == 1
    assert set(index["e_id"]) == {"a_fwd", "a_rev", "b"}


def test_join_aggregates_multiple_structures_on_same_link(tmp_path):
    nbi_path, links_path = _toy_links_and_nbi(tmp_path)
    index, _stats = build_bridge_index(nbi_path, links_path, max_distance_m=100.0)

    row = index.loc[index["e_id"] == "a_fwd"].iloc[0]
    assert row["deck_width_m"] == pytest.approx(15.0)  # mean(10, 20)
    assert row["structure_length_m"] == pytest.approx(70.0)  # sum(30, 40)
    assert row["n_structures"] == 2


def test_join_flags_both_directions_of_bidirectional_pair(tmp_path):
    # A single structure ties at distance 0 to both directional siblings
    # sharing identical geometry -- both should be flagged as bridges, not
    # just one arbitrarily picked side.
    nbi_path, links_path = _toy_links_and_nbi(tmp_path)
    index, _stats = build_bridge_index(nbi_path, links_path, max_distance_m=100.0)
    assert {"a_fwd", "a_rev"}.issubset(set(index["e_id"]))
