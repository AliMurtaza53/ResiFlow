"""Sioux Falls multihazard testbed fixtures."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from resiflow.hazards.scenario_registry import HazardScenario, lookup_scenario_by_env

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = REPO_ROOT / "scripts"
GENERATOR = SCRIPTS / "testbed" / "generate_synthetic_hazards.py"

MULTIHAZARD_VARIANT = "toy_sioux_falls_multihazard"


def scenario_for(
    hazard_type: str,
    *,
    flood_subtype: str | None = None,
    event_id: str = "1",
) -> HazardScenario:
    """Resolve unique scenario_param for a multihazard test case."""
    env_backup = {
        "RESIFLOW_HAZARD_TYPE": os.environ.get("RESIFLOW_HAZARD_TYPE"),
        "RESIFLOW_FLOOD_SUBTYPE": os.environ.get("RESIFLOW_FLOOD_SUBTYPE"),
    }
    try:
        if hazard_type == "snow":
            os.environ["RESIFLOW_HAZARD_TYPE"] = "snow"
            os.environ.pop("RESIFLOW_FLOOD_SUBTYPE", None)
        elif hazard_type == "flood":
            os.environ.pop("RESIFLOW_HAZARD_TYPE", None)
            if flood_subtype:
                os.environ["RESIFLOW_FLOOD_SUBTYPE"] = flood_subtype
            else:
                os.environ.pop("RESIFLOW_FLOOD_SUBTYPE", None)
        else:
            os.environ["RESIFLOW_HAZARD_TYPE"] = hazard_type
            os.environ.pop("RESIFLOW_FLOOD_SUBTYPE", None)

        found = lookup_scenario_by_env()
        if found is None:
            raise ValueError(f"No registered scenario for hazard_type={hazard_type!r} flood_subtype={flood_subtype!r}")
        return found
    finally:
        for key, value in env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


# Unique scenario_param per hazard (Script 2/4 CLI arg 1).
SCENARIO_KEYS = {
    "flood": scenario_for("flood", flood_subtype="flood_surface").scenario_param,
    "flood_surface": scenario_for("flood", flood_subtype="flood_surface").scenario_param,
    "flood_river": scenario_for("flood", flood_subtype="flood_river").scenario_param,
    "flood_coastal": scenario_for("flood", flood_subtype="flood_coastal").scenario_param,
    "earthquake": scenario_for("earthquake").scenario_param,
    "landslide": scenario_for("landslide").scenario_param,
    "winter_storm": scenario_for("winter_storm").scenario_param,
    "snow": scenario_for("snow").scenario_param,
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
    env["NIRD_RECOVERY_DB_PATH"] = str(tmp_path / "toy_data" / "dbs" / "recovery_30_1.duckdb")

    scenario = scenario_for(
        hazard_type if hazard_type != "flood" else "flood",
        flood_subtype=flood_subtype,
    )
    env["RESIFLOW_SCENARIO_PARAM"] = str(scenario.scenario_param)

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
