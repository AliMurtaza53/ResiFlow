"""End-to-end snow disruption test on the Sioux Falls testbed."""

from __future__ import annotations

import pandas as pd

from sioux_falls_fixtures import (
    SNOW_SCENARIO_KEY_MM,
    build_sioux_falls_dataset,
    run_snow_pipeline_scripts,
    sioux_falls_env,
)
from toy_pipeline_fixtures import disruption_dir


def test_sioux_falls_snow_pipeline_reroute_bridge_bottleneck(tmp_path) -> None:
    config_path, spec, _links = build_sioux_falls_dataset(tmp_path, hazard="snow")
    env = sioux_falls_env(tmp_path, config_path, hazard="snow")
    run_snow_pipeline_scripts(env, snow_key_mm=SNOW_SCENARIO_KEY_MM)

    links_path = (
        disruption_dir(tmp_path, env, depth_key=SNOW_SCENARIO_KEY_MM) / "links" / "road_links_1.gpq"
    )
    assert links_path.exists(), f"missing {links_path}"
    links = pd.read_parquet(links_path)

    assert len(links) == spec.link_count
    assert links["hazard_type"].iloc[0] == "snow"
    assert links["intensity_unit"].iloc[0] == "mm_snow"

    snow_mm = pd.to_numeric(links.get("snow_depth_max_mm", 0), errors="coerce").fillna(0)
    max_speed = pd.to_numeric(links.get("max_speed", 999), errors="coerce").fillna(999)
    assert int((snow_mm > 0).sum()) == len(spec.flooded_edge_ids)
    assert int((max_speed == 0).sum()) >= len(spec.flooded_edge_ids)
