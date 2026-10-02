"""Unit checks for NBI↔FAF bridge-match QA helpers."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from diagnose_nbi_faf_bridge_matches import (  # noqa: E402
    bearing_delta_deg,
    faf_tier,
    name_overlap,
    nbi_tier,
    tier_jump,
)


def test_tiers_and_jumps():
    assert nbi_tier("Urban - Principal Arterial - Interstate") == "interstate"
    assert nbi_tier("Rural - Local") == "local"
    assert faf_tier(11, "motorway") == "interstate"
    assert faf_tier(22, "motorway_link") == "ramp"
    assert faf_tier(14, "primary") == "principal_arterial"
    assert tier_jump("local", "interstate") >= 3
    assert tier_jump("interstate", "interstate") == 0


def test_name_overlap_route_and_tokens():
    hit = name_overlap("I-95 NB", "I-95")
    assert hit["name_hit"]
    assert "95" in hit["shared_routes"] or hit["n_shared_tokens"] > 0

    miss = name_overlap("RIVER CREEK PKWY", "I-66 RAMP")
    assert miss["both_named"]
    assert not miss["name_hit"]


def test_bearing_delta():
    assert bearing_delta_deg(10, 100) == pytest.approx(90)
    assert bearing_delta_deg(0, 170) == pytest.approx(10)
