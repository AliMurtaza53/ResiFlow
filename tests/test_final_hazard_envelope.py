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


def test_new_madrid_is_m77_with_companions_and_m75_stays_available():
    from resiflow.hazards.liquefaction import SCENARIO_MAGNITUDE_MW
    from resiflow.hazards.real_events import (
        RealEarthquakeNewMadridM77ScenarioSource as Eq77,
        RealEarthquakeNewMadridScenarioSource as Eq75,
        RealLandslideNewMadridM77Source as Ls77,
    )

    by_param = {s.scenario_param: s for s in load_hazard_manifest(MANIFEST)}
    assert by_param[403].hazard_subtype == "earthquake_new_madrid_m77_scenario"
    assert by_param[503].hazard_subtype == "landslide_new_madrid_m77"
    assert Eq77.hazard_subtype == by_param[403].hazard_subtype and Eq77.sa1p0_companion and Eq77.liquefaction_companion
    assert Ls77.hazard_subtype == by_param[503].hazard_subtype
    assert Eq75.hazard_subtype == "earthquake_new_madrid_m75_scenario"
    assert SCENARIO_MAGNITUDE_MW["earthquake_new_madrid_m77_scenario"] == 7.7
