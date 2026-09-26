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
