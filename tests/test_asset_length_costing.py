"""Asset-length costing: NBI structure_length / NTI tunnel_length, not full FAF edge."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from importlib import import_module

_damage = import_module("3_damage_analysis")
compute_damage_values = _damage.compute_damage_values
compute_damage_fraction = _damage.compute_damage_fraction


class _ToyCurve:
    def __init__(self, label):
        self.label = label

    def damage_fraction(self, depth):
        return self.label  # identity stand-in, just need to see which curve ran


def _toy_curves():
    return {c: _ToyCurve(c) for c in ("C1", "C2", "C3", "C4", "C5", "C6")}


def _toy_costs():
    return {
        "bridge_surface": {
            "minor": {"min": 1.0, "max": 2.0},
        },
        "tunnel": {
            "Interstate": {"min": 10.0, "max": 20.0},
            "m_lt8_urb": {"min": 10.0, "max": 20.0},
        },
        "road": {
            "Interstate": {"min": 1.0, "max": 2.0},
            "m_lt8_urb": {"min": 1.0, "max": 2.0},
        },
    }


def test_bridge_uses_structure_length_not_faf_length():
    costs = _toy_costs()
    # FAF edge 5000m but NBI structure only 40m → cost must use 40.
    mn, mx, mean = compute_damage_values(
        length=5000.0,
        flood_type="surface",
        damage_fraction=1.0,
        road_classification="motorway",
        form_of_way="Dual Carriageway",
        urban=1,
        lanes=2,
        road_label="bridge",
        damage_level="minor",
        damage_values=costs,
        bridge_width=10.0,
        structure_length_m=40.0,
    )
    assert mn == pytest.approx(10.0 * 40.0 * 1.0)
    assert mx == pytest.approx(10.0 * 40.0 * 2.0)


def test_bridge_requires_structure_length():
    with pytest.raises(ValueError, match="structure_length_m"):
        compute_damage_values(
            length=5000.0,
            flood_type="surface",
            damage_fraction=1.0,
            road_classification="motorway",
            form_of_way="Dual Carriageway",
            urban=1,
            lanes=2,
            road_label="bridge",
            damage_level="minor",
            damage_values=_toy_costs(),
            bridge_width=10.0,
        )


def test_tunnel_fraction_caps_at_inventory_length():
    costs = _toy_costs()
    # FAF 2000m, tunnel inventory 200m → cost on 200m (lanes * km * unit).
    mn, mx, _ = compute_damage_values(
        length=2000.0,
        flood_type="surface",
        damage_fraction=1.0,
        road_classification="motorway",
        form_of_way="Dual Carriageway",
        urban=1,
        lanes=2,
        road_label="tunnel",
        damage_level="minor",
        damage_values=costs,
        tunnel_length_m=200.0,
    )
    # asset_length=200m → 0.2 km * 2 lanes * unit
    assert mn == pytest.approx(0.2 * 2 * 10.0)
    assert mx == pytest.approx(0.2 * 2 * 20.0)


def test_damage_fraction_family_uses_nhs_not_name_when_available():
    curves = _toy_curves()
    # "primary" is "major" by the legacy name-based proxy, so the OLD logic
    # would have picked C3/C4 regardless of real NHS status. A real,
    # non-null nhs_designation should now govern instead:
    on_nhs = compute_damage_fraction(
        "primary", False, "road", 0.5, curves, nhs_designation=1
    )
    assert on_nhs[0] == "C3" and on_nhs[2] == "C4"  # NHS, no tunnel -> simple

    # A road genuinely off NHS goes to C5/C6 (ordinary) even though its
    # name-based classification would have called it "major" -- pass
    # pandas NA (a present-but-null per-row value) rather than Python None
    # (which instead means "no nhs_designation column on this network at
    # all", tested separately below) to distinguish the two.
    import pandas as pd

    off_nhs = compute_damage_fraction(
        "primary", False, "road", 0.5, curves, nhs_designation=pd.NA
    )
    assert off_nhs[0] == "C5" and off_nhs[2] == "C6"


def test_damage_fraction_sophisticated_requires_nhs_and_tunnel():
    curves = _toy_curves()
    result = compute_damage_fraction(
        "primary", False, "tunnel", 0.5, curves, nhs_designation=1
    )
    assert result[0] == "C1" and result[2] == "C2"  # NHS + tunnel -> sophisticated


def test_damage_fraction_falls_back_to_legacy_proxy_without_nhs_column():
    curves = _toy_curves()
    # nhs_designation truly absent (column doesn't exist on this network) --
    # legacy name/trunk_road-based "major road" proxy, unchanged behavior.
    major_tunnel = compute_damage_fraction("primary", False, "tunnel", 0.5, curves)
    assert major_tunnel[0] == "C1" and major_tunnel[2] == "C2"
    major_road = compute_damage_fraction("primary", False, "road", 0.5, curves)
    assert major_road[0] == "C3" and major_road[2] == "C4"
    minor_road = compute_damage_fraction("tertiary", False, "road", 0.5, curves)
    assert minor_road[0] == "C5" and minor_road[2] == "C6"


def test_tunnel_requires_inventory_length():
    with pytest.raises(ValueError, match="tunnel_length_m"):
        compute_damage_values(
            length=2000.0,
            flood_type="surface",
            damage_fraction=1.0,
            road_classification="motorway",
            form_of_way="Dual Carriageway",
            urban=1,
            lanes=2,
            road_label="tunnel",
            damage_level="minor",
            damage_values=_toy_costs(),
        )
