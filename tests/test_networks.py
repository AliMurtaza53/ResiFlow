"""Tests for the modular network adapter layer."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pytest

from resiflow.networks import (
    coerce_profile_dict,
    load_assignment_profiles,
    load_network_mapping,
    normalize_network_links,
)
from resiflow.networks.base import LEGACY_COMBINED_TO_TIER, TIER_TO_LEGACY_COMBINED

REPO_ROOT = Path(__file__).resolve().parents[1]
PARAMETERS = REPO_ROOT / "parameters"


def test_coerce_profile_dict_accepts_legacy_keys() -> None:
    raw = {"M": 2400, "A_dual": 2200, "A_single": 1700, "B": 1000}
    coerced = coerce_profile_dict(raw)
    assert coerced["freeway"] == 2400
    assert coerced["arterial"] == 2200
    assert coerced["collector"] == 1700
    assert coerced["local_access"] == 1000


def test_faf5_mapping_local_stays_arterial_for_parity() -> None:
    mapping = load_network_mapping("faf5", params_root=PARAMETERS)
    assert mapping["network_class_to_assignment_tier"]["local"] == "arterial"


def test_normalize_faf5_links_writes_tiers_and_legacy_label() -> None:
    links = pd.DataFrame(
        {
            "e_id": ["1", "2", "3", "4"],
            "road_classification": ["motorway", "primary", "tertiary", "local"],
        }
    )
    out = normalize_network_links(links, source="faf5", params_root=str(PARAMETERS))
    assert out.loc[0, "assignment_tier"] == "freeway"
    assert out.loc[0, "combined_label"] == TIER_TO_LEGACY_COMBINED["freeway"]
    assert out.loc[1, "assignment_tier"] == "arterial"
    assert out.loc[2, "assignment_tier"] == "collector"
    assert out.loc[3, "assignment_tier"] == "arterial"
    assert out.loc[0, "damage_profile"] == "major_road"
    assert out.loc[2, "damage_profile"] == "minor_road"


def test_normalize_osm_links_from_highway_column() -> None:
    links = pd.DataFrame(
        {
            "e_id": ["1", "2"],
            "highway": ["motorway", "residential"],
        }
    )
    out = normalize_network_links(links, source="osm", params_root=str(PARAMETERS))
    assert out.loc[0, "network_source"] == "osm"
    assert out.loc[0, "assignment_tier"] == "freeway"
    assert out.loc[1, "assignment_tier"] == "local_access"


def test_load_assignment_profiles_from_bundled_json() -> None:
    profiles = load_assignment_profiles(PARAMETERS)
    assert profiles["flow_cap_plph"]["freeway"] == 2400
    assert profiles["congestion_factor"]["collector"] == 0.05


def test_load_assignment_profiles_legacy_fallback(tmp_path: Path) -> None:
    (tmp_path / "flow_cap_plph_dict.json").write_text(
        json.dumps({"M": 10, "A_dual": 9, "A_single": 8, "B": 7}),
        encoding="utf-8",
    )
    (tmp_path / "flow_breakpoint_dict.json").write_text(
        json.dumps({"M": 1, "A_dual": 2, "A_single": 3, "B": 4}),
        encoding="utf-8",
    )
    (tmp_path / "free_flow_speed_dict.json").write_text(
        json.dumps({"M": 70, "A_dual": 60, "A_single": 55, "B": 35}),
        encoding="utf-8",
    )
    (tmp_path / "urban_speed_cap.json").write_text(
        json.dumps({"M": 55, "A_dual": 45, "A_single": 35, "B": 30}),
        encoding="utf-8",
    )
    (tmp_path / "min_speed_cap.json").write_text(
        json.dumps({"M": 10, "A_dual": 8, "A_single": 7, "B": 5}),
        encoding="utf-8",
    )
    profiles = load_assignment_profiles(tmp_path)
    assert profiles["flow_cap_plph"]["freeway"] == 10
    assert profiles["flow_breakpoint"]["local_access"] == 4


@pytest.mark.parametrize(
    ("legacy", "tier"),
    list(LEGACY_COMBINED_TO_TIER.items()),
)
def test_legacy_combined_label_roundtrip(legacy: str, tier: str) -> None:
    if legacy not in {"M", "A_dual", "A_single", "B"}:
        pytest.skip("extended legacy labels")
    assert TIER_TO_LEGACY_COMBINED[tier] == legacy
