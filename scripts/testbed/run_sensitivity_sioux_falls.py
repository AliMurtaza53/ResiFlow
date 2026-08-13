#!/usr/bin/env python3
"""Sioux Falls Scripts 1-4 -> Script 5 (direct+indirect) -> Morris sensitivity panel.

One-shot testbed runner that mirrors ``run_multihazard_sioux_falls.py``:

1. builds the Sioux Falls testbed and runs the pipeline (Scripts 1-4),
2. runs ``5_sensitivity_analysis_{direct,indirect}.py`` pointed at the testbed
   layout via ``NIRD_RESULTS_ROOT`` / ``NIRD_RESULTS_VARIANT`` (so they read
   ``<results>/{damage,rerouting}_analysis/toy_sioux_falls/...`` instead of the
   CONUS ``revision`` layout) and write ``sensitivity_analysis/morris_*.csv``,
3. renders the panel via ``viz_data_loaders.plot_sensitivity_panels``.

Script 5 is run tolerantly: the observational Morris design is data-hungry, and
the tiny toy network may not yield enough damaged links for the *direct* target
-- in that case the panel is drawn from whichever target(s) did produce a CSV.

Writes to ``results/sensitivity_panel/`` by default (outside pytest basetemp).

Example::

    python scripts/testbed/run_sensitivity_sioux_falls.py
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"
SRC_DIR = REPO_ROOT / "src"
VIZ_DIR = REPO_ROOT / "scripts" / "visualizations"
for _p in (str(SRC_DIR), str(TESTS_DIR), str(VIZ_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

VARIANT = "toy_sioux_falls"


def _run_script5(name: str, env: dict[str, str], results_root: Path) -> int:
    """Run a Script 5 file against the testbed layout; tolerate failure."""
    env5 = dict(env)
    env5["NIRD_RESULTS_ROOT"] = str(results_root)
    env5["NIRD_RESULTS_VARIANT"] = VARIANT
    env5["MPLBACKEND"] = "Agg"  # make Script 5's plt.show() a headless no-op
    print(f"> {name}")
    proc = subprocess.run(
        [sys.executable, str(REPO_ROOT / "scripts" / name)],
        cwd=REPO_ROOT,
        env=env5,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print(f"  {name} exited {proc.returncode} (continuing without it).")
        tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-4:]
        for line in tail:
            print("    " + line)
    return proc.returncode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "results" / "sensitivity_panel",
        help="Workspace + outputs root (default: results/sensitivity_panel)",
    )
    parser.add_argument(
        "--skip-pipeline",
        action="store_true",
        help="Reuse an existing workspace's Scripts 1-4 outputs (re-run only Script 5)",
    )
    args = parser.parse_args()

    from sioux_falls_fixtures import build_sioux_falls_dataset, sioux_falls_env
    from toy_pipeline_fixtures import run_pipeline_scripts
    from viz_data_loaders import load_morris_sensitivity, plot_sensitivity_panels
    import matplotlib

    matplotlib.use("Agg")

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    workspace = output_root / "workspace"

    if args.skip_pipeline:
        if not (workspace / "results").exists():
            print(
                f"--skip-pipeline set but no pipeline outputs under {workspace / 'results'}.",
                file=sys.stderr,
            )
            return 1
        env = sioux_falls_env(workspace, workspace / "config.json")
    else:
        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.mkdir(parents=True)
        print("Building heterogeneous Sioux Falls testbed + running Scripts 1-4 ...")
        config_path, _spec, _ = build_sioux_falls_dataset(workspace, heterogeneous=True)
        env = sioux_falls_env(workspace, config_path)
        run_pipeline_scripts(env)

    results_root = workspace / "results"
    print("Running Script 5 (direct + indirect) on the testbed layout ...")
    _run_script5("5_sensitivity_analysis_direct.py", env, results_root)
    _run_script5("5_sensitivity_analysis_indirect.py", env, results_root)

    df = load_morris_sensitivity(results_root)
    if df.empty:
        print(
            "No morris_*.csv produced. Script 5's observational Morris found "
            "insufficient data on the toy testbed (expected for the small "
            "network's direct-damage target).",
            file=sys.stderr,
        )
        return 1

    print(f"Sensitivity targets available: {sorted(df['target'].unique())}")
    fig, _ = plot_sensitivity_panels(df, variant=VARIANT)
    panel_path = output_root / "sensitivity_panel.png"
    fig.savefig(panel_path, dpi=200, bbox_inches="tight")

    print(f"Wrote morris CSVs under: {results_root / 'sensitivity_analysis'}")
    print(f"Wrote panel: {panel_path}")
    print(
        "\nView with the shared loader:\n"
        f"  python scripts/summarize_scenario_run.py --sensitivity "
        f"--results-root {results_root} --variant {VARIANT}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
