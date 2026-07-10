"""Winter storm disruption pipeline."""

from __future__ import annotations

from pathlib import Path

from resiflow.disruption.build import build_winter_storm_link_disruption
from resiflow.disruption.pipeline_intensity import run_intensity_disruption
from resiflow.disruption.winter_storm import intersections_with_winter_storm
from resiflow.hazards.sioux_falls_multihazard import WinterStormHazardSource
from resiflow.utils import load_config


def run_winter_storm_disruption(
    scenario_key: int,
    event_key: str,
    *,
    base_path=None,
    hazard_source=None,
) -> None:
    if base_path is None:
        base_path = Path(load_config()["paths"]["soge_clusters"])
    base_path = Path(base_path)
    if hazard_source is None:
        hazard_source = WinterStormHazardSource(base_path)
    run_intensity_disruption(
        scenario_key,
        event_key,
        hazard_label="winter_storm",
        hazard_source=hazard_source,
        intersections_fn=intersections_with_winter_storm,
        build_link_fn=build_winter_storm_link_disruption,
        base_path=base_path,
    )
