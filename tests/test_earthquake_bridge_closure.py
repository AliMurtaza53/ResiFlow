"""A complete-damage (severe) bridge closes at day 0, however bridges are labelled."""

import pandas as pd
import pytest

from resiflow.fragility.earthquake_operational import apply_max_speed_to_links


def _links(**extra):
    d = {
        "damage_level_max": ["severe", "severe", "no"],
        "free_flow_speeds": [50.0, 50.0, 50.0],
    }
    d.update(extra)
    return pd.DataFrame(d)


@pytest.mark.parametrize("hazard", ["earthquake", "landslide"])
def test_severe_bridge_closed_via_road_label(hazard):
    out = apply_max_speed_to_links(_links(road_label=["bridge", "road", "bridge"]), hazard=hazard)
    assert out["max_speed"].tolist() == [0.0, 5.0, 50.0]


def test_severe_bridge_closed_via_road_bridge_flag():
    out = apply_max_speed_to_links(_links(road_bridge=["yes", "no", "no"]))
    assert out["max_speed"].tolist() == [0.0, 5.0, 50.0]
