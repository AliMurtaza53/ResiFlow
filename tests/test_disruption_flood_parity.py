"""Flood disruption parity and link-record contract tests."""

from __future__ import annotations

import pandas as pd
import pytest

from resiflow.disruption.link_record import LinkDisruptionRecord, apply_legacy_flood_columns
from resiflow.fragility.flood_operational import (
    apply_max_speed_to_links,
    compute_maximum_speed_on_flooded_roads,
)
from sioux_falls_fixtures import build_sioux_falls_dataset, sioux_falls_env
from toy_pipeline_fixtures import disruption_dir, run_pipeline_scripts


def test_compute_maximum_speed_matches_vectorized_rule() -> None:
    depth_m = 0.25  # 25 cm
    free_flow = 50.0
    scalar = compute_maximum_speed_on_flooded_roads(depth_m, free_flow, threshold=30)
    frame = apply_max_speed_to_links(
        pd.DataFrame({"flood_depth_max": [depth_m], "free_flow_speeds": [free_flow]}),
        depth_key=30,
    )
    assert scalar == pytest.approx(float(frame["max_speed"].iloc[0]))


def test_link_disruption_record_from_flood_row() -> None:
    row = pd.Series(
        {
            "e_id": "e1",
            "flood_depth_max": 0.5,
            "max_speed": 0.0,
            "damage_level_max": "moderate",
        }
    )
    rec = LinkDisruptionRecord.from_flood_row(row, event_id=1, depth_key=30)
    assert rec.e_id == "e1"
    assert rec.intensity_primary == pytest.approx(0.5)
    assert rec.damage_level_max == "moderate"


def test_apply_legacy_flood_columns_adds_canonical_fields() -> None:
    df = pd.DataFrame({"e_id": ["e1"], "flood_depth_max": [0.1], "damage_level_max": ["minor"]})
    out = apply_legacy_flood_columns(df, depth_key=30, event_id=1)
    assert out["hazard_type"].iloc[0] == "flood"
    assert out["intensity_unit"].iloc[0] == "m_depth"
    assert out["scenario_param"].iloc[0] == 30


def test_sioux_falls_disruption_link_metrics(tmp_path) -> None:
    config_path, spec, _source_links = build_sioux_falls_dataset(tmp_path)
    env = sioux_falls_env(tmp_path, config_path)
    run_pipeline_scripts(env)

    links_path = disruption_dir(tmp_path, env) / "links" / "road_links_1.gpq"
    assert links_path.exists(), f"missing {links_path}"
    links = pd.read_parquet(links_path)

    assert len(links) == spec.link_count
    flood_depth = pd.to_numeric(links.get("flood_depth_max", 0), errors="coerce").fillna(0)
    max_speed = pd.to_numeric(links.get("max_speed", 999), errors="coerce").fillna(999)
    assert int((flood_depth > 0).sum()) == len(spec.flooded_edge_ids)
    assert int((max_speed == 0).sum()) >= len(spec.flooded_edge_ids)
    assert "hazard_type" in links.columns
    assert links["hazard_type"].iloc[0] == "flood"
