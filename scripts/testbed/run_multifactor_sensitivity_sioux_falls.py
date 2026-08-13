#!/usr/bin/env python3
"""Proper *multi-factor* Morris sensitivity of Sioux Falls direct + indirect cost.

This generalizes ``run_congestion_sensitivity_sioux_falls.py`` from a single
scalar (``congestion_factor``, k=1) to a proper multi-factor sampled Morris
screen. Unlike ``scripts/5_sensitivity_analysis_{direct,indirect}.py`` -- which
run Morris on *observational* pipeline rows (statistically invalid: the rows are
not a sampled trajectory design, so ``morris.analyze`` misattributes correlated
factors) -- this driver:

1. builds the (heterogeneous) Sioux Falls testbed once,
2. draws a proper Morris trajectory sample over a **multiplier** applied to each
   genuine, perturbable scalar *input*,
3. re-runs the full pipeline (Scripts 1-4) once per sample, and
4. analyzes the elementary effects on BOTH targets (direct damage and indirect
   rerouting cost) from the same runs.

Perturbable input factors (the "Balanced 8"). Each is swept as a multiplicative
factor ``m`` around its baseline; both targets are read from every run:

    Network / hazard / cost (patched in the staged input files):
      * flood_depth   -- scale the hazard raster depths        (direct + indirect)
      * damage_ratio  -- scale the fragility damage-curve values (direct + indirect)
      * damage_value  -- scale the unit repair/replacement costs (direct)
      * averageWidth  -- scale link widths                       (direct: bridge area)
      * lanes         -- scale link lane counts                  (direct: length x lanes)
      * demand_scale  -- scale OD Car21 volumes                  (indirect: flows)

    Scalar parameters (patched in the staged ``unified_parameters.json``):
      * value_of_time         -- scale VOT $/hr                  (indirect: time cost)
      * flood_closure_threshold -- scale the closure depth (cm)  (indirect: closures)

WHY NOT the other "selected" columns? The observational Scripts 5 list ~13
factors, but most are not perturbable scalar inputs and so cannot receive a
valid elementary effect:
  * ``road_classification``, ``form_of_way``, ``trunk_road``, ``urban``,
    ``road_label``, ``flood_type`` are categorical/boolean per-link attributes --
    a scalar multiplier is meaningless.
  * ``damage_level`` is derived from depth + fragility (already moved by
    ``flood_depth`` / ``damage_ratio``).
  * ``disrupted_flow`` / ``change_flow`` are derived assignment *outputs*.
  * ``length`` is geometry-derived, not a scalar column (excluded to avoid
    rescaling geometry).
  * ``congestion_factor`` is structurally inert (the pipeline routes on
    free-flow link costs; see ``run_congestion_sensitivity_sioux_falls.py``).

Perturbation is applied by patching the staged input files (not the fixture), so
``tests/sioux_falls_fixtures.py`` and the pinned pipeline tests are untouched.
Each sample writes ``baseline * m`` from an in-memory snapshot taken once after
the single build, so perturbations never compound.

Outputs (default ``results/multifactor_sensitivity/``):
  * ``sensitivity_analysis/morris_direct.csv`` and ``morris_indirect.csv``
    (same schema as the observational Script-5 outputs, so
    ``summarize_scenario_run.py --sensitivity`` and ``plot_sensitivity_panels``
    read them directly -- but these are the *sampled*, statistically valid
    version).
  * ``samples.csv`` -- every run's multipliers + both cost targets.
  * ``sensitivity_panel.png`` -- the mu*-sigma two-panel figure.

Runtime: Morris needs ``r * (k + 1)`` pipeline runs. k=8, so r=4 -> 36 runs
(~30 min on the toy network; each Scripts 1-4 run is ~50 s).

Example::

    python scripts/testbed/run_multifactor_sensitivity_sioux_falls.py -r 4
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass
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

# Display name -> short id. Order defines the Morris problem variable order.
FACTORS: tuple[tuple[str, str], ...] = (
    ("Flood Depth", "flood_depth"),
    ("Damage Ratio", "damage_ratio"),
    ("Unit Asset Value", "damage_value"),
    ("Road Width", "averageWidth"),
    ("Lanes", "lanes"),
    ("Demand", "demand_scale"),
    ("Value of Time", "value_of_time"),
    ("Closure Threshold", "flood_closure_threshold"),
)
_VOT_FALLBACK = {"car": 18.50, "lgv": 31.00, "ogv": 32.50, "psv": 18.50, "rail": 22.90}
_CLOSURE_FALLBACK_CM = 30.0


@dataclass
class Baselines:
    """In-memory snapshot of the pristine staged inputs (taken once)."""

    links_gdf: "object"
    links_path: Path
    passenger_od: pd.DataFrame
    passenger_path: Path
    freight_od: pd.DataFrame
    freight_path: Path
    ratio_df: pd.DataFrame
    ratio_path: Path
    ratio_class_cols: list[str]
    cost_path: Path
    cost_sheets: dict[str, pd.DataFrame]
    raster_bands: dict[Path, "np.ndarray"]
    raster_profiles: dict[Path, dict]
    unified_path: Path
    unified: dict
    vot_baseline: dict[str, float]
    closure_baseline_cm: float


def _snapshot(toy_data: Path, staged_params: Path) -> Baselines:
    import geopandas as gpd
    import rasterio

    links_path = toy_data / "inputs" / "networks" / "faf5" / "faf5_road_links.gpq"
    passenger_path = (
        toy_data / "lodes_data" / "processed"
        / "lodes_passenger_assignment_od_jt00_2022.parquet"
    )
    freight_path = toy_data / "inputs" / "census_datasets" / "faf5_od_matrix.pq"
    ratio_path = toy_data / "damage_curves" / "damage_ratio_road_flood.xlsx"
    cost_path = toy_data / "asset_costs" / "damage_cost_road_flood.xlsx"
    raster_dir = toy_data / "inputs" / "test_141node_50m"
    unified_path = staged_params / "unified_parameters.json"

    ratio_df = pd.read_excel(ratio_path)
    ratio_class_cols = [c for c in ratio_df.columns if c.lower() != "intensity"]

    cost_sheets = pd.read_excel(cost_path, sheet_name=None)  # dict[str, DataFrame]

    raster_bands: dict[Path, np.ndarray] = {}
    raster_profiles: dict[Path, dict] = {}
    for tif in sorted(raster_dir.glob("va_hazard_class50_141node_*.tif")):
        with rasterio.open(tif) as src:
            raster_bands[tif] = src.read(1)
            raster_profiles[tif] = src.profile.copy()

    unified = json.loads(unified_path.read_text(encoding="utf-8")) if unified_path.exists() else {}
    vot_baseline = dict(
        (unified.get("cost_time", {}) or {}).get("vot_usd_per_hour", _VOT_FALLBACK)
    )
    closure_baseline_cm = float(
        (unified.get("hazard_disruption", {}) or {}).get(
            "flood_closure_threshold_cm", _CLOSURE_FALLBACK_CM
        )
    )

    return Baselines(
        links_gdf=gpd.read_parquet(links_path),
        links_path=links_path,
        passenger_od=pd.read_parquet(passenger_path),
        passenger_path=passenger_path,
        freight_od=pd.read_parquet(freight_path),
        freight_path=freight_path,
        ratio_df=ratio_df,
        ratio_path=ratio_path,
        ratio_class_cols=ratio_class_cols,
        cost_path=cost_path,
        cost_sheets={name: df.copy() for name, df in cost_sheets.items()},
        raster_bands=raster_bands,
        raster_profiles=raster_profiles,
        unified_path=unified_path,
        unified=unified,
        vot_baseline=vot_baseline,
        closure_baseline_cm=closure_baseline_cm,
    )


def _apply_sample(base: Baselines, m: dict[str, float]) -> None:
    """Write every staged input as ``baseline * m`` for the given multipliers."""
    import rasterio

    # --- network links: lanes + averageWidth ---
    links = base.links_gdf.copy()
    links["lanes"] = (
        (pd.to_numeric(links["lanes"], errors="coerce").fillna(1.0) * m["lanes"])
        .round()
        .clip(lower=1)
        .astype(int)
    )
    links["averageWidth"] = (
        pd.to_numeric(links["averageWidth"], errors="coerce").fillna(0.0)
        * m["averageWidth"]
    )
    links.to_parquet(base.links_path)

    # --- OD demand (passenger + freight share preserved) ---
    for df, path in (
        (base.passenger_od, base.passenger_path),
        (base.freight_od, base.freight_path),
    ):
        out = df.copy()
        out["Car21"] = out["Car21"] * m["demand_scale"]
        out.to_parquet(path, index=False)

    # --- fragility damage ratios (kept in [0, 1]) ---
    ratio = base.ratio_df.copy()
    for col in base.ratio_class_cols:
        ratio[col] = (ratio[col] * m["damage_ratio"]).clip(lower=0.0, upper=1.0)
    ratio.to_excel(base.ratio_path, index=False)

    # --- unit asset costs (all sheets: roads + bridge variants) ---
    with pd.ExcelWriter(base.cost_path) as writer:
        for name, df in base.cost_sheets.items():
            scaled = df.copy()
            for col in ("min", "max", "mean"):
                if col in scaled.columns:
                    scaled[col] = scaled[col] * m["damage_value"]
            scaled.to_excel(writer, sheet_name=name, index=False)

    # --- hazard raster depths (all variants) ---
    for tif, band in base.raster_bands.items():
        with rasterio.open(tif, "w", **base.raster_profiles[tif]) as dst:
            dst.write((band * m["flood_depth"]).astype(band.dtype), 1)

    # --- scalar parameters (VOT + closure threshold) ---
    unified = json.loads(json.dumps(base.unified))  # deep copy
    unified.setdefault("cost_time", {})["vot_usd_per_hour"] = {
        k: v * m["value_of_time"] for k, v in base.vot_baseline.items()
    }
    unified.setdefault("hazard_disruption", {})["flood_closure_threshold_cm"] = (
        base.closure_baseline_cm * m["flood_closure_threshold"]
    )
    base.unified_path.write_text(json.dumps(unified, indent=2), encoding="utf-8")


def _restore(base: Baselines) -> None:
    """Rewrite the staged inputs to their pristine baseline (m = 1)."""
    _apply_sample(base, {sid: 1.0 for _, sid in FACTORS})


def _morris_frame(problem: dict, X: np.ndarray, Y: np.ndarray) -> pd.DataFrame:
    from SALib.analyze import morris as morris_analyze

    Si = morris_analyze.analyze(problem, X, Y)
    return pd.DataFrame(
        {
            "Parameters": [name for name, _ in FACTORS],
            "S1": Si["mu"],
            "ST": Si["sigma"],
            "S1_abs": Si["mu_star"],
            "S1_abs_conf": Si["mu_star_conf"],
        }
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root", type=Path,
        default=REPO_ROOT / "results" / "multifactor_sensitivity",
        help="Where CSVs + figure are written (default: results/multifactor_sensitivity)",
    )
    parser.add_argument(
        "-r", "--num-trajectories", type=int, default=4,
        help="Morris trajectories; pipeline runs = r*(k+1) = r*9 for k=8 (default 4 -> 36 runs)",
    )
    parser.add_argument("--m-low", type=float, default=0.5, help="Lower multiplier bound")
    parser.add_argument("--m-high", type=float, default=2.0, help="Upper multiplier bound")
    parser.add_argument("--num-levels", type=int, default=4, help="Morris grid levels")
    args = parser.parse_args()

    from sioux_falls_fixtures import build_sioux_falls_dataset, sioux_falls_env
    from toy_pipeline_fixtures import run_pipeline_scripts
    from viz_data_loaders import format_cost, plot_sensitivity_panels, summarize_single_scenario
    from SALib.sample.morris import sample as morris_sample
    import matplotlib

    matplotlib.use("Agg")

    output_root = args.output_root.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    workspace = output_root / "workspace"
    if workspace.exists():
        shutil.rmtree(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    print("Building heterogeneous Sioux Falls testbed ...")
    config_path, _spec, _ = build_sioux_falls_dataset(workspace, heterogeneous=True)
    env = sioux_falls_env(workspace, config_path)

    toy_data = workspace / "toy_data"
    staged_params = toy_data / "inputs" / "parameters"
    # Make constants.py / flood_operational.py (imported fresh per subprocess)
    # resolve unified_parameters.json from the staged copy we patch here.
    env["RESIFLOW_PARAMETERS_ROOT"] = str(staged_params)
    env["MPLBACKEND"] = "Agg"

    base = _snapshot(toy_data, staged_params)

    names = [sid for _, sid in FACTORS]
    problem = {
        "num_vars": len(names),
        "names": names,
        "bounds": [[args.m_low, args.m_high]] * len(names),
    }
    X = morris_sample(problem, N=args.num_trajectories, num_levels=args.num_levels)
    print(
        f"Morris sample: {X.shape[0]} pipeline runs "
        f"(r={args.num_trajectories}, k={len(names)})"
    )

    results_root = workspace / "results"
    rows: list[dict] = []
    Y_direct: list[float] = []
    Y_indirect: list[float] = []
    try:
        for i, sample in enumerate(X):
            m = {sid: float(v) for sid, v in zip(names, sample)}
            _apply_sample(base, m)
            run_pipeline_scripts(env)
            summary = summarize_single_scenario(
                results_root, variant=VARIANT, depth_key=DEPTH_KEY, flood_key=FLOOD_KEY
            )
            direct = float(summary.get("direct_damage_usd", 0.0) or 0.0)
            freight = float(summary.get("rerouting_cost_freight_usd", 0.0) or 0.0)
            passenger = float(summary.get("rerouting_cost_passenger_usd", 0.0) or 0.0)
            indirect = freight + passenger
            Y_direct.append(direct)
            Y_indirect.append(indirect)
            rows.append(
                {"sample": i, **m, "direct_damage_usd": direct,
                 "rerouting_total_usd": indirect}
            )
            print(
                f"[{i + 1}/{X.shape[0]}] "
                f"direct={format_cost(direct, variant=VARIANT)} "
                f"indirect={format_cost(indirect, variant=VARIANT)}"
            )
    finally:
        _restore(base)

    direct_df = _morris_frame(problem, X, np.asarray(Y_direct, dtype=float))
    indirect_df = _morris_frame(problem, X, np.asarray(Y_indirect, dtype=float))

    sens_dir = output_root / "sensitivity_analysis"
    sens_dir.mkdir(parents=True, exist_ok=True)
    direct_df.to_csv(sens_dir / "morris_direct.csv", index=False)
    indirect_df.to_csv(sens_dir / "morris_indirect.csv", index=False)

    samples_df = pd.DataFrame(rows)
    samples_df.to_csv(output_root / "samples.csv", index=False)

    panel_df = pd.concat(
        [direct_df.assign(target="direct"), indirect_df.assign(target="indirect")],
        ignore_index=True,
    )
    fig, _ = plot_sensitivity_panels(panel_df, variant=VARIANT)
    panel_path = output_root / "sensitivity_panel.png"
    fig.savefig(panel_path, dpi=200, bbox_inches="tight")

    print("\n=== Direct damage (Morris, sampled) ===")
    print(direct_df.to_string(index=False))
    print("\n=== Indirect rerouting (Morris, sampled) ===")
    print(indirect_df.to_string(index=False))
    print(f"\nWrote: {sens_dir / 'morris_direct.csv'}")
    print(f"Wrote: {sens_dir / 'morris_indirect.csv'}")
    print(f"Wrote: {output_root / 'samples.csv'}")
    print(f"Wrote: {panel_path}")

    for label, ys in (("direct", Y_direct), ("indirect", Y_indirect)):
        if pd.Series(ys).round(6).nunique() <= 1:
            print(
                f"\nWARNING: {label} target did not vary across samples -- every "
                "sampled factor is inert for it on this testbed.",
                file=sys.stderr,
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
