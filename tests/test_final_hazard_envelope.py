"""The final 4 hazards x 2 events manifest resolves to unique, registered scenarios."""

from pathlib import Path

from resiflow.hazards.real_events import resolve_real_source  # noqa: F401
from resiflow.hazards.scenario_registry import load_hazard_manifest, lookup_scenario_by_param

MANIFEST = Path(__file__).resolve().parent.parent / "parameters" / "hazards.final_envelope.json"


def test_final_envelope_is_four_hazards_by_two_events():
    sc = load_hazard_manifest(MANIFEST)
    assert len(sc) == 8
    assert len({s.scenario_param for s in sc}) == 8
    by_type = {}
    for s in sc:
        by_type.setdefault(s.hazard_type, []).append(s.scenario_param)
    assert {k: sorted(v) for k, v in by_type.items()} == {
        "flood": [304, 305],
        "earthquake": [403, 404],
        "landslide": [502, 503],
        "winter_storm": [601, 603],
    }


def test_manifest_matches_builtin_registry():
    for s in load_hazard_manifest(MANIFEST):
        b = lookup_scenario_by_param(s.scenario_param)
        assert b is not None and b.hazard_type == s.hazard_type
        assert b.hazard_subtype == s.hazard_subtype or (b.hazard_subtype is None and s.hazard_subtype is None)
