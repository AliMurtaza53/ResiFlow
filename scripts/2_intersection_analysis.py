"""Script 2: intersection analysis for road links and hazard rasters.

``scenario_param`` (CLI arg 1) is the unique output-path key under
``disruption_analysis/<variant>/<scenario_param>/``. Operational fragility
thresholds (flood depth cm, snow mm, etc.) are resolved from ``hazards.json``,
``RESIFLOW_SCENARIO_PARAM``, or env hazard type — and may differ from
``scenario_param`` for multihazard comparison runs.

Legacy single-hazard runs: when no manifest matches, ``scenario_param`` also
serves as the closure threshold (e.g. ``30`` cm flood depth).

``event_key`` selects the hazard scenario variant (1=base, 2=low, 3=high).
Use ``all`` or a comma-separated list such as ``2,3`` to process multiple toy
events in one process.
"""

from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from resiflow.disruption.build import run_disruption
from resiflow.disruption.pipeline import run_flood_disruption
from resiflow.exposure.raster_line import (
    clip_features,
    intersect_features_with_raster,
    load_analysis_boundary,
    subset_features_to_raster_extent,
)
from resiflow.fragility.flood_categorical import (
    compute_damage_level_on_flooded_roads,
    compute_damage_levels_on_flooded_roads_vectorized,
)
from resiflow.fragility.flood_operational import compute_maximum_speed_on_flooded_roads
from resiflow.disruption.flood import features_with_damage, intersections_with_damage
from resiflow.disruption.io import first_existing, log_summary, validate_output
from resiflow.geo_runtime import configure_geo_runtime

configure_geo_runtime()

# Backward-compatible re-exports for callers that imported Script 2 helpers.
__all__ = [
    "run_flood_disruption",
    "subset_features_to_raster_extent",
    "load_analysis_boundary",
    "intersect_features_with_raster",
    "clip_features",
    "compute_maximum_speed_on_flooded_roads",
    "compute_damage_level_on_flooded_roads",
    "compute_damage_levels_on_flooded_roads_vectorized",
    "intersections_with_damage",
    "features_with_damage",
    "first_existing",
    "validate_output",
    "log_summary",
]


def main(scenario_param: int, event_key: str) -> None:
    """Thin wrapper around hazard-agnostic disruption (flood default, snow via RESIFLOW_HAZARD_TYPE)."""
    run_disruption(scenario_param, event_key)


if __name__ == "__main__":
    start_time = time.time()
    logging.basicConfig(
        format="%(asctime)s %(process)d %(filename)s %(levelname)s %(message)s",
        level=logging.INFO,
    )
    print("=" * 60)
    print("SCRIPT 2: Intersection Analysis - STARTING")
    print("=" * 60)
    try:
        depth_key = sys.argv[1]
        event_key = sys.argv[2]
        print(f"CLI Args: scenario_param={depth_key}, event_key={event_key}")
        logging.info(f"Script 2 starting with scenario_param={depth_key}, event_key={event_key}")
        main(int(depth_key), str(event_key))
        elapsed = time.time() - start_time
        print("=" * 60)
        print(f"SCRIPT 2: COMPLETED SUCCESSFULLY in {elapsed:.2f} seconds")
        print("=" * 60)
        logging.info(f"Script 2 completed in {elapsed:.2f} seconds")
    except IndexError:
        error_msg = "Please enter depth_key and event_key!"
        logging.error(error_msg)
        print(f"ERROR: {error_msg}")
        print(f"Usage: python {sys.argv[0]} <depth_key> <event_key>")
        print("  depth_key: flood depth threshold in cm (e.g., 15, 30, 60)")
        print("  event_key (toy dataset): 1=base, 2=low, 3=high")
        sys.exit(1)
    except Exception as exc:
        elapsed = time.time() - start_time
        logging.exception(f"Unexpected error in script 2 after {elapsed:.2f}s")
        print(f"FATAL ERROR: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
