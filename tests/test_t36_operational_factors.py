"""Assert T36 day-1 factors load and apply (bridge vs road fork)."""
from __future__ import annotations

import pandas as pd

from resiflow.fragility.earthquake_operational import apply_max_speed_to_links
from resiflow.fragility.landslide_operational import (
    apply_max_speed_to_links as apply_ls,
)


def test_t36_earthquake_landslide_operational_factors() -> None:
    links = pd.DataFrame(
        {
            "e_id": ["b1", "r1", "b2"],
            "road_bridge": ["yes", "no", "yes"],
            "damage_level_max": ["moderate", "moderate", "severe"],
            "free_flow_speeds": [60.0, 60.0, 60.0],
        }
    )
    eq = apply_max_speed_to_links(links, hazard="earthquake")
    # bridge moderate → 0.30; road moderate → 0.25; bridge severe → 0
    assert abs(eq["max_speed"].iloc[0] - 18.0) < 1e-9, eq["max_speed"].tolist()
    assert abs(eq["max_speed"].iloc[1] - 15.0) < 1e-9, eq["max_speed"].tolist()
    assert abs(eq["max_speed"].iloc[2] - 0.0) < 1e-9, eq["max_speed"].tolist()

    ls = apply_ls(links)
    assert abs(ls["max_speed"].iloc[0] - 18.0) < 1e-9
    assert abs(ls["max_speed"].iloc[1] - 15.0) < 1e-9
