#!/usr/bin/env python3
"""Pass B vs full reassignment spillover diagnostic for testbed-scale networks."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


def _run(cmd: list[str], env: dict[str, str], cwd: Path) -> None:
    print(">", " ".join(cmd))
    subprocess.run(cmd, cwd=cwd, env=env, check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tmp-root", type=Path, help="pytest-style temp folder for fixture build")
    parser.add_argument("--out-md", type=Path, help="Markdown summary output path")
    args = parser.parse_args()

    tmp_root = args.tmp_root or Path(tempfile.mkdtemp(prefix="passb_diag_"))
    env = os.environ.copy()
    env["PYTHONPATH"] = str(REPO_ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")

    # Build multihazard Sioux Falls fixture and Pass A baseline.
    build_py = f"""
from pathlib import Path
from multihazard_sioux_falls_fixtures import build_multihazard_dataset, multihazard_env, MULTIHAZARD_VARIANT, SCENARIO_KEYS
from toy_pipeline_fixtures import run_script
tmp = Path({str(tmp_root)!r})
config, _ = build_multihazard_dataset(tmp)
base_env = multihazard_env(tmp, config, hazard_type='flood', flood_subtype='flood_surface')
run_script('1_network_flow_model_revision.py', ['1', '1'], base_env)
run_script('2_intersection_analysis.py', [str(SCENARIO_KEYS['flood']), '1'], base_env)
"""
    subprocess.run([PYTHON, "-c", build_py], cwd=REPO_ROOT / "tests", env=env, check=True)

    config_path = tmp_root / "config.json"
    from pathlib import Path as P

    sys.path.insert(0, str(REPO_ROOT / "tests"))
    from multihazard_sioux_falls_fixtures import multihazard_env, SCENARIO_KEYS

    pass_b_env = multihazard_env(tmp_root, config_path, hazard_type="flood", flood_subtype="flood_surface")
    full_env = dict(pass_b_env)
    scenario = str(SCENARIO_KEYS["flood"])

    # Pass B style: event candidates (Script 1 with damaged edges export is out of scope here).
    # Compare Script 4 with default candidate loader vs forcing full overlay via SAMPLE_OD_N=0 and legacy mode.
    _run([PYTHON, str(REPO_ROOT / "scripts" / "3_damage_analysis.py")], pass_b_env, REPO_ROOT)
    _run([PYTHON, str(REPO_ROOT / "scripts" / "4_rerouting_and_recovery_scenario_loop.py"), scenario, "1", "1", "1"], pass_b_env, REPO_ROOT)

    # Re-run Script 4 is expensive; report documents placeholder until full Pass B wiring is added.
    summary = {
        "variant": pass_b_env.get("RESIFLOW_RESULTS_VARIANT"),
        "note": "Pass B vs full reassignment comparison requires Pass B Script 1 event_candidates; placeholder run completed Script 4 once.",
        "scenario_key": scenario,
        "event_key": "1",
    }
    md = (
        "# Pass B spillover diagnostic (testbed)\n\n"
        f"- Variant: `{summary['variant']}`\n"
        f"- Scenario/event: `{summary['scenario_key']}` / `{summary['event_key']}`\n"
        f"- {summary['note']}\n"
        "- Next step: export `event_damaged_edges`, rerun Script 1 Pass B, diff per-OD costs vs full reassignment.\n"
    )
    print(md)
    if args.out_md:
        args.out_md.parent.mkdir(parents=True, exist_ok=True)
        args.out_md.write_text(md, encoding="utf-8")
        print(f"Wrote {args.out_md}")
    else:
        out = tmp_root / "pass_b_spillover_summary.md"
        out.write_text(md, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
