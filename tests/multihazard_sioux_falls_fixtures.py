"""Sioux Falls multihazard testbed fixtures."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
GENERATOR = SCRIPTS / "testbed" / "generate_synthetic_hazards.py"

MULTIHAZARD_VARIANT = "toy_sioux_falls_multihazard"

# Scenario params (Script 2 arg 1) per hazard type.
SCENARIO_KEYS = {
    "flood": 30,
    "earthquake": 25,
    "landslide": 100,
    "winter_storm": 100,
    "snow": 150,
}


def build_multihazard_dataset(tmp_path: Path) -> tuple[Path, Path]:
    """Build Sioux Falls toy data + synthetic multihazard rasters."""
    from sioux_falls_fixtures import build_sioux_falls_dataset

    config_path, _spec, _links = build_sioux_falls_dataset(tmp_path, hazard="flood")
    toy_data_dir = tmp_path / "toy_data"
    subprocess.run(
        [sys.executable, str(GENERATOR), "--output-dir", str(toy_data_dir)],
        cwd=REPO_ROOT,
        check=True,
    )
    return config_path, toy_data_dir


def multihazard_env(
    tmp_path: Path,
    config_path: Path,
    *,
    hazard_type: str = "flood",
    flood_subtype: str | None = None,
) -> dict[str, str]:
    from sioux_falls_fixtures import sioux_falls_env

    env = sioux_falls_env(tmp_path, config_path, hazard="flood")
    env["NIRD_RESULTS_VARIANT"] = MULTIHAZARD_VARIANT
    env["RESIFLOW_RESULTS_VARIANT"] = MULTIHAZARD_VARIANT
    env["NIRD_BASE_SCENARIO_OUT_DIR"] = str(
        tmp_path / "results" / "base_scenario" / MULTIHAZARD_VARIANT
    )
    env["NIRD_ENABLE_PASSENGER_REROUTING"] = "1"
    env["RESIFLOW_ENABLE_PASSENGER_REROUTING"] = "1"

    if hazard_type == "snow":
        env["RESIFLOW_HAZARD_TYPE"] = "snow"
    elif hazard_type == "flood":
        env.pop("RESIFLOW_HAZARD_TYPE", None)
        if flood_subtype:
            env["RESIFLOW_FLOOD_SUBTYPE"] = flood_subtype
    else:
        env["RESIFLOW_HAZARD_TYPE"] = hazard_type

    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + str(REPO_ROOT)
    return env
