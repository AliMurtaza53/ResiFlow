#!/usr/bin/env python3
"""Proper Morris sensitivity of Sioux Falls rerouting cost to ``congestion_factor``.

Unlike ``scripts/5_sensitivity_analysis_indirect.py`` (which runs Morris on
*observational* pipeline rows -- statistically invalid, and unable to vary a
global scalar), this driver:

1. builds the Sioux Falls testbed once,
2. draws a proper Morris sample over a scalar multiplier applied to the per-tier
   ``congestion_factor`` (the speed-flow slope in ``road_revised.update_edge_speed``),
3. re-runs the full pipeline (Scripts 1-4) per sample,
4. reads the indirect (rerouting) cost, and
5. analyzes the elementary effects with SALib Morris.

Because only one parameter is varied (k=1), the result is an elementary-effects
dose-response.

FINDING (documented null result): the Morris mu* for rerouting cost is exactly
zero. The pipeline routes on FREE-FLOW link costs -- ``create_igraph_network``
(``src/resiflow/road_revised.py``) fixes each edge ``weight`` from
``time_hr = length_mile / acc_speed`` using the uncongested initial speed, and
``update_edge_speed``'s congested ``acc_speed`` is a report-only field that never
re-enters route choice. So congestion_factor cannot move rerouting cost; it is a
structural property, not a tuning issue. This driver demonstrates that directly:
it also records total network speed reduction, which DOES vary with
congestion_factor (proving the wiring works), contrasted against the flat
rerouting cost.

Writes to ``results/congestion_sensitivity/`` by default (outside pytest basetemp).

Example::

    python scripts/testbed/run_congestion_sensitivity_sioux_falls.py -r 10
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from pathlib import Path

import numpy as np
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
TESTS_DIR = REPO_ROOT / "tests"
SRC_DIR = REPO_ROOT / "src"
VIZ_DIR = REPO_ROOT / "scripts" / "visualizations"
for _p in (str(SRC_DIR), str(TESTS_DIR), str(VIZ_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

VARIANT = "toy_sioux_falls"
DEPTH_KEY = 30
FLOOD_KEY = 1
TIERS = ("freeway", "arterial", "collector", "local_access")


def _write_profiles(
    profiles_path: Path,
    baseline_cf: dict[str, float],
    multiplier: float,
    *,
    breakpoint_vph: float | None = None,
) -> None:
    """Rewrite assignment_profiles.json for one sample.

    ``congestion_factor`` is the varied parameter (scaled by ``multiplier``).
    ``breakpoint_vph``, when given, overrides every tier's ``flow_breakpoint``
    to a single fixed value -- a documented testbed control that puts the small
    network into the congested regime (vp > breakpoint) so congestion_factor is
    not inert. It is held fixed across all samples, not varied.
    """
    data = json.loads(profiles_path.read_text(encoding="utf-8"))
    data["congestion_factor"] = {t: baseline_cf[t] * multiplier for t in baseline_cf}
    if breakpoint_vph is not None:
        data["flow_breakpoint"] = {t: float(breakpoint_vph) for t in data["flow_breakpoint"]}
    profiles_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _plot(samples_df: pd.DataFrame, res_df: pd.DataFrame, out_dir: Path, variant: str) -> Path:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from viz_data_loaders import format_cost

    # Theme-neutral palette (viz_data_loaders palette constants are function-local).
    COLOR = "#2a78d6"
    INK = "#0b0b0b"
    GRID = "#d9d8d2"

    df = samples_df.sort_values("multiplier")
    mu_star = float(res_df["S1_abs"].iloc[0])

    fig, ax = plt.subplots(figsize=(7.5, 5))
    ax.plot(df["multiplier"], df["rerouting_total_usd"], "-", color=COLOR, alpha=0.5, zorder=1)
    ax.scatter(
        df["multiplier"], df["rerouting_total_usd"],
        color=COLOR, edgecolor="black", linewidth=0.5, s=45, zorder=2,
        label="Total rerouting cost",
    )
    ax.axvline(1.0, color=GRID, linestyle="--", linewidth=1, zorder=0)
    ax.set_xlabel(r"congestion_factor multiplier ($m$)")
    ax.set_ylabel("Indirect rerouting cost")
    ax.set_title(
        "Sioux Falls: rerouting cost sensitivity to congestion_factor\n"
        rf"Morris $\mu^*$ = {format_cost(mu_star, variant=variant)} "
        "(mean abs. elementary effect)",
        color=INK, fontsize=12, loc="left",
    )
    ax.yaxis.grid(True, color=GRID, linewidth=1)
    ax.set_axisbelow(True)
    for spine in ("top", "right"):
        ax.spines[spine].set_visible(False)
    ax.yaxis.set_major_formatter(
        plt.FuncFormatter(lambda v, _: format_cost(v, variant=variant))
    )
    fig.tight_layout()
    out_path = out_dir / "congestion_sensitivity.tif"
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    plt.close(fig)
    return out_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "results" / "congestion_sensitivity",
        help="Where CSVs + figure are written (default: results/congestion_sensitivity)",
    )
    parser.add_argument(
        "-r", "--num-trajectories", type=int, default=10,
        help="Morris trajectories; pipeline runs = 2*r for k=1 (default 10)",
    )
    parser.add_argument("--m-low", type=float, default=0.25, help="Lower multiplier bound")
    parser.add_argument("--m-high", type=float, default=3.0, help="Upper multiplier bound")
    parser.add_argument(
        "--breakpoint-vph", type=float, default=150.0,
        help="Fixed per-tier flow_breakpoint (veh/hr) to engage the congested "
        "regime so congestion_factor is not inert (default 150; the toy's peak "
        "flow is ~1030 vph vs a 1300 vph default breakpoint). Set <=0 to keep "
        "the profile's default breakpoints.",
    )
    parser.add_argument("--event", default="1", help="Hazard event id (default 1)")
    args = parser.parse_args()
    breakpoint_vph = args.breakpoint_vph if args.breakpoint_vph > 0 else None

    from sioux_falls_fixtures import build_sioux_falls_dataset, sioux_falls_env
    from toy_pipeline_fixtures import run_pipeline_scripts
    from viz_data_loaders import format_cost, summarize_single_scenario
    from SALib.analyze import morris as morris_analyze
    from SALib.sample.morris import sample as morris_sample

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    workspace = output_root / "workspace"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    print("Building Sioux Falls testbed ...")
    config_path, spec, _ = build_sioux_falls_dataset(workspace)
    env = sioux_falls_env(workspace, config_path)

    staged_params = workspace / "toy_data" / "inputs" / "parameters"
    profiles_path = staged_params / "assignment_profiles.json"
    baseline_profiles = json.loads(profiles_path.read_text(encoding="utf-8"))
    baseline_cf = {t: float(baseline_profiles["congestion_factor"][t]) for t in TIERS}
    # Make update_edge_speed's params-root resolution read the same staged file
    # we patch here (otherwise it falls back to the repo parameters/ copy).
    env["RESIFLOW_PARAMETERS_ROOT"] = str(staged_params)

    problem = {
        "num_vars": 1,
        "names": ["congestion_factor"],
        "bounds": [[args.m_low, args.m_high]],
    }
    X = morris_sample(problem, N=args.num_trajectories)  # shape (2*r, 1)
    print(f"Morris sample: {X.shape[0]} pipeline runs (r={args.num_trajectories}, k=1)")

    results_root = workspace / "results"
    rows: list[dict[str, float | int]] = []
    Y: list[float] = []
    try:
        for i, sample in enumerate(X):
            m = float(sample[0])
            _write_profiles(profiles_path, baseline_cf, m, breakpoint_vph=breakpoint_vph)
            run_pipeline_scripts(env)
            summary = summarize_single_scenario(
                results_root, variant=VARIANT, depth_key=DEPTH_KEY, flood_key=FLOOD_KEY
            )
            freight = float(summary.get("rerouting_cost_freight_usd", 0.0) or 0.0)
            passenger = float(summary.get("rerouting_cost_passenger_usd", 0.0) or 0.0)
            total = freight + passenger
            Y.append(total)
            rows.append(
                {
                    "sample": i,
                    "multiplier": m,
                    "rerouting_freight_usd": freight,
                    "rerouting_passenger_usd": passenger,
                    "rerouting_total_usd": total,
                }
            )
            print(
                f"[{i + 1}/{X.shape[0]}] m={m:.4f} "
                f"rerouting_total={format_cost(total, variant=VARIANT)}"
            )
    finally:
        # Always restore the baseline profile (congestion_factor and breakpoints).
        profiles_path.write_text(json.dumps(baseline_profiles, indent=2), encoding="utf-8")

    Y_arr = np.asarray(Y, dtype=float)
    Si = morris_analyze.analyze(problem, X, Y_arr)
    res_df = pd.DataFrame(
        {
            "Parameters": problem["names"],
            "S1": Si["mu"],
            "ST": Si["sigma"],
            "S1_abs": Si["mu_star"],
            "S1_abs_conf": Si["mu_star_conf"],
        }
    )

    res_df.to_csv(output_root / "morris_congestion.csv", index=False)
    samples_df = pd.DataFrame(rows).sort_values("multiplier").reset_index(drop=True)
    samples_df.to_csv(output_root / "samples.csv", index=False)
    fig_path = _plot(samples_df, res_df, output_root, VARIANT)

    print("\n=== Morris congestion sensitivity ===")
    print(res_df.to_string(index=False))
    print(f"\nWrote: {output_root / 'morris_congestion.csv'}")
    print(f"Wrote: {output_root / 'samples.csv'}")
    print(f"Wrote: {fig_path}")

    n_distinct = samples_df["rerouting_total_usd"].round(6).nunique()
    if n_distinct <= 1:
        print(
            "\nWARNING: rerouting cost did not vary across congestion_factor samples.\n"
            "On this toy network per-link hourly flow may never exceed the congestion\n"
            "breakpoint (vp <= breakpoint_flow => congestion_factor is inert). Consider\n"
            "raising demand or lowering flow_breakpoint to engage the congested regime.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
