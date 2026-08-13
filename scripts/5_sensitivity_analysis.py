# %%
"""Script 5 -- Sensitivity analysis over the Script 1-4 cost outputs.

The four upstream scripts produce, per hazard scenario, a small set of headline
costs:

    * direct damage            (Script 3 fragility x exposure)
    * rerouting cost (freight)  (Script 4 recovery loop)
    * rerouting cost (passenger)(Script 4 recovery loop)
    * isolation                 (Script 4 trip isolations)

This script asks a follow-up question: *how much do those headline costs move
when the key model parameters move?* It runs a one-at-a-time (OAT) sweep over
the scalar parameters declared in ``parameters/unified_parameters.json`` and
reports, per scenario, how each cost component responds -- plus a tornado table
ranking parameters by the swing they induce in the combined total.

Running the full Script 1-4 pipeline once per parameter x level would be far too
expensive for an interactive sweep, so this script does **not** re-run the
network flow model. Instead it:

  1. Establishes a *baseline* per-scenario cost vector. When real Script 1-4
     outputs are on disk it reads them via the shared summary-table loader;
     otherwise (or with ``--sample``) it falls back to an illustrative baseline
     so the script is runnable standalone and always "generates sample
     results".
  2. Perturbs each parameter across a low->high range and applies a documented
     elasticity model (fractional change in each cost component per fractional
     change in the parameter) to produce perturbed cost vectors.

The elasticities are transparent, first-order approximations -- not a
substitute for re-running the pipeline -- and every response is emitted to CSV
so the assumptions are auditable. Swap in pipeline-derived elasticities by
editing ``default_parameters`` once you have paired runs to calibrate against.

Examples
--------
    # Standalone sample run (no data root required):
    python scripts/5_sensitivity_analysis.py --sample

    # Use real Script 1-4 outputs as the baseline:
    python scripts/5_sensitivity_analysis.py --results-root results --variant revision
"""

from __future__ import annotations

import argparse
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(1, str(REPO_ROOT))

import numpy as np
import pandas as pd

# Cost components carried through the sweep (order is display order).
COMPONENTS: tuple[str, ...] = (
    "direct_damage",
    "rerouting_freight",
    "rerouting_passenger",
    "isolation",
)

# Illustrative per-scenario baseline (thousands of USD). Mirrors the six-hazard
# panel in notebooks/raw_cost_estimate_panel.ipynb; used when real Script 1-4
# outputs are unavailable or when --sample is passed. These are NOT measured
# figures -- they only exist so the sweep is demonstrable standalone.
SAMPLE_BASELINE: tuple[dict[str, float | int | str], ...] = (
    {"hazard_label": "Flood surface", "scenario_param": 301,
     "direct_damage": 0.4, "rerouting_freight": 0.9, "rerouting_passenger": 9.8, "isolation": 2.5},
    {"hazard_label": "Flood river", "scenario_param": 302,
     "direct_damage": 3.1, "rerouting_freight": 1.9, "rerouting_passenger": 21.0, "isolation": 6.2},
    {"hazard_label": "Flood coastal", "scenario_param": 303,
     "direct_damage": 0.2, "rerouting_freight": 0.9, "rerouting_passenger": 9.8, "isolation": 2.3},
    {"hazard_label": "Earthquake", "scenario_param": 401,
     "direct_damage": 0.5, "rerouting_freight": 1.9, "rerouting_passenger": 21.1, "isolation": 7.8},
    {"hazard_label": "Landslide", "scenario_param": 501,
     "direct_damage": 0.4, "rerouting_freight": 0.9, "rerouting_passenger": 9.8, "isolation": 12.4},
    {"hazard_label": "Winter storm", "scenario_param": 601,
     "direct_damage": 0.4, "rerouting_freight": 0.9, "rerouting_passenger": 9.8, "isolation": 5.6},
)

# Assumed per-isolated-trip cost (USD) used only to turn the real pipeline's
# isolation *flow* into an isolation *cost* component for the baseline vector.
ISOLATION_UNIT_COST_USD = 50.0


@dataclass(frozen=True)
class SensitivityParameter:
    """One scalar parameter to sweep, with its response elasticities.

    Attributes
    ----------
    name : short slug used in output tables.
    section, key : location in unified_parameters.json (for the baseline value).
    default : hardcoded fallback baseline value (the historical literal).
    low_mult, high_mult : multipliers on the baseline value bounding the sweep.
    elasticities : fractional change in each cost component per unit fractional
        change in the parameter. e.g. elasticity 1.0 => component scales 1:1
        with the parameter; -0.5 => component falls 5% when the parameter rises
        10%; 0.0 => component is insensitive to the parameter.
    label : human-readable description.
    """

    name: str
    section: str
    key: str
    default: float
    low_mult: float
    high_mult: float
    elasticities: dict[str, float] = field(default_factory=dict)
    label: str = ""


def default_parameters(params_root: Path | str | None = None) -> list[SensitivityParameter]:
    """Build the parameter set, reading baseline values from unified_parameters.

    Falls back to the hardcoded literal for each value if the unified parameter
    file (or the resiflow import chain) is unavailable -- so this works in a
    bare checkout with no data root.
    """

    def resolve(section: str, key: str, default: float) -> float:
        try:
            from resiflow.parameters import get_parameter

            return float(get_parameter(section, key, default, params_root=params_root))
        except Exception:
            return float(default)

    specs = [
        SensitivityParameter(
            name="demand_scale", section="assignment_ue_bpr", key="demand_scale",
            default=1.0, low_mult=0.80, high_mult=1.20,
            elasticities={"direct_damage": 0.0, "rerouting_freight": 1.0,
                          "rerouting_passenger": 1.0, "isolation": 0.6},
            label="Global OD demand multiplier",
        ),
        SensitivityParameter(
            name="bpr_alpha", section="assignment_ue_bpr", key="bpr_alpha",
            default=0.15, low_mult=0.50, high_mult=1.50,
            elasticities={"direct_damage": 0.0, "rerouting_freight": 0.35,
                          "rerouting_passenger": 0.45, "isolation": 0.05},
            label="BPR congestion coefficient (alpha)",
        ),
        SensitivityParameter(
            name="bpr_beta", section="assignment_ue_bpr", key="bpr_beta",
            default=4.0, low_mult=0.75, high_mult=1.25,
            elasticities={"direct_damage": 0.0, "rerouting_freight": 0.50,
                          "rerouting_passenger": 0.60, "isolation": 0.10},
            label="BPR congestion exponent (beta)",
        ),
        SensitivityParameter(
            name="gbp_to_usd", section="conversions", key="gbp_to_usd",
            default=1.27, low_mult=0.90, high_mult=1.10,
            elasticities={"direct_damage": 0.0, "rerouting_freight": 1.0,
                          "rerouting_passenger": 1.0, "isolation": 0.0},
            label="GBP->USD currency conversion",
        ),
        SensitivityParameter(
            name="fuel_usd_per_litre", section="conversions", key="default_fuel_usd_per_litre",
            default=0.95, low_mult=0.70, high_mult=1.30,
            elasticities={"direct_damage": 0.0, "rerouting_freight": 0.40,
                          "rerouting_passenger": 0.30, "isolation": 0.0},
            label="Fuel price (USD/litre) -> operating cost",
        ),
        SensitivityParameter(
            name="flood_closure_threshold_cm", section="hazard_disruption",
            key="flood_closure_threshold_cm",
            default=30.0, low_mult=0.50, high_mult=1.50,
            # A higher closure threshold means fewer links are shut, so costs
            # fall as the parameter rises -> negative elasticities.
            elasticities={"direct_damage": -0.30, "rerouting_freight": -0.50,
                          "rerouting_passenger": -0.50, "isolation": -0.70},
            label="Flood closure depth threshold (cm)",
        ),
        SensitivityParameter(
            name="damage_depth_scale", section="hazard_disruption",
            key="earthquake_script3_depth_scale",
            default=0.5, low_mult=0.50, high_mult=1.50,
            elasticities={"direct_damage": 1.0, "rerouting_freight": 0.20,
                          "rerouting_passenger": 0.20, "isolation": 0.40},
            label="Hazard->damage depth scale (severity)",
        ),
    ]
    return [
        SensitivityParameter(
            name=s.name, section=s.section, key=s.key,
            default=resolve(s.section, s.key, s.default),
            low_mult=s.low_mult, high_mult=s.high_mult,
            elasticities=s.elasticities, label=s.label,
        )
        for s in specs
    ]


def load_baseline_scenarios(
    results_root: Path | None,
    variant: str | None,
    event_key: int,
    *,
    use_sample: bool,
) -> tuple[pd.DataFrame, str, str]:
    """Return (baseline_df, source, unit_label).

    baseline_df has columns: hazard_label, scenario_param, and one column per
    COMPONENT holding the baseline cost. ``source`` is "pipeline" or "sample".
    """
    if not use_sample and results_root is not None:
        try:
            df = _load_pipeline_baseline(results_root, variant, event_key)
            if df is not None and not df.empty:
                return df, "pipeline", "USD"
            logging.warning(
                "No on-disk Script 1-4 outputs found under %s; using sample baseline.",
                results_root,
            )
        except Exception as exc:  # missing loaders / data root, etc.
            logging.warning("Could not load pipeline baseline (%s); using sample baseline.", exc)

    rows = [dict(r) for r in SAMPLE_BASELINE]
    return pd.DataFrame(rows), "sample", "KUSD (illustrative)"


def _load_pipeline_baseline(
    results_root: Path,
    variant: str | None,
    event_key: int,
) -> pd.DataFrame | None:
    """Read real Script 1-4 cost outputs via the shared summary-table loader."""
    viz_dir = REPO_ROOT / "scripts" / "visualizations"
    if str(viz_dir) not in sys.path:
        sys.path.insert(0, str(viz_dir))
    from viz_data_loaders import build_multihazard_summary_table, resolve_variant  # type: ignore

    resolved_variant = variant or _resolve_variant(results_root)
    summary = build_multihazard_summary_table(
        results_root, resolved_variant, event_key=int(event_key)
    )
    if summary.empty:
        return None
    if "data_present" in summary.columns:
        summary = summary[summary["data_present"].fillna(False).astype(bool)]
    if summary.empty:
        return None

    iso_flow = (
        pd.to_numeric(summary.get("isolation_flow", 0.0), errors="coerce").fillna(0.0)
    )
    out = pd.DataFrame({
        "hazard_label": summary.get("hazard_label", summary.get("scenario_param")).astype(str),
        "scenario_param": pd.to_numeric(summary["scenario_param"], errors="coerce").astype("Int64"),
        "direct_damage": pd.to_numeric(summary["direct_damage_usd"], errors="coerce").fillna(0.0),
        "rerouting_freight": pd.to_numeric(summary["rerouting_cost_freight_usd"], errors="coerce").fillna(0.0),
        "rerouting_passenger": pd.to_numeric(summary["rerouting_cost_passenger_usd"], errors="coerce").fillna(0.0),
        "isolation": iso_flow * ISOLATION_UNIT_COST_USD,
    })
    return out.reset_index(drop=True)


def _resolve_variant(results_root: Path) -> str:
    base = results_root / "base_scenario"
    if base.exists():
        variants = sorted(p.name for p in base.iterdir() if p.is_dir())
        if variants:
            return variants[0]
    return "revision"


def sweep_levels(low_mult: float, high_mult: float, n_levels: int) -> np.ndarray:
    """Evenly spaced multipliers spanning [low, high], always including 1.0."""
    pts = list(np.linspace(low_mult, high_mult, max(2, n_levels)))
    if not any(abs(p - 1.0) < 1e-9 for p in pts):
        pts.append(1.0)
    return np.array(sorted(set(round(p, 6) for p in pts)))


def perturb_component(base_value: float, elasticity: float, frac_change: float) -> float:
    """First-order elasticity response, floored at zero (costs can't go negative)."""
    return max(0.0, base_value * (1.0 + elasticity * frac_change))


def run_oat_sweep(
    baseline: pd.DataFrame,
    parameters: list[SensitivityParameter],
    *,
    n_levels: int,
    noise: float,
    rng: np.random.Generator,
) -> pd.DataFrame:
    """Long tidy frame: one row per (parameter, level, scenario)."""
    records: list[dict[str, float | int | str]] = []
    for param in parameters:
        for mult in sweep_levels(param.low_mult, param.high_mult, n_levels):
            frac_change = float(mult) - 1.0
            param_value = param.default * float(mult)
            for _, srow in baseline.iterrows():
                rec: dict[str, float | int | str] = {
                    "parameter": param.name,
                    "parameter_label": param.label,
                    "multiplier": float(mult),
                    "parameter_value": param_value,
                    "frac_change": frac_change,
                    "hazard_label": srow["hazard_label"],
                    "scenario_param": srow["scenario_param"],
                }
                total = 0.0
                for comp in COMPONENTS:
                    base_value = float(srow[comp])
                    value = perturb_component(
                        base_value, param.elasticities.get(comp, 0.0), frac_change
                    )
                    if noise > 0.0 and abs(frac_change) > 0.0:
                        value *= 1.0 + rng.normal(0.0, noise)
                        value = max(0.0, value)
                    rec[comp] = value
                    total += value
                rec["combined_total"] = total
                records.append(rec)
    return pd.DataFrame.from_records(records)


def build_tornado(oat: pd.DataFrame, parameters: list[SensitivityParameter]) -> pd.DataFrame:
    """Per-parameter swing in the (scenario-summed) combined total across the sweep.

    Compares the low- and high-multiplier ends against the baseline (mult=1.0),
    aggregating combined_total over all scenarios.
    """
    totals = (
        oat.groupby(["parameter", "multiplier"], as_index=False)["combined_total"].sum()
    )
    rows: list[dict[str, float | str]] = []
    for param in parameters:
        sub = totals[totals["parameter"] == param.name]
        if sub.empty:
            continue
        base_mult = sub.iloc[(sub["multiplier"] - 1.0).abs().argmin()]
        base_total = float(base_mult["combined_total"])
        low_total = float(sub.loc[sub["multiplier"].idxmin(), "combined_total"])
        high_total = float(sub.loc[sub["multiplier"].idxmax(), "combined_total"])
        swing = abs(high_total - low_total)
        rows.append({
            "parameter": param.name,
            "parameter_label": param.label,
            "low_multiplier": float(sub["multiplier"].min()),
            "high_multiplier": float(sub["multiplier"].max()),
            "combined_total_low": low_total,
            "combined_total_base": base_total,
            "combined_total_high": high_total,
            "swing": swing,
            "swing_pct_of_base": (swing / base_total * 100.0) if base_total else 0.0,
        })
    tornado = pd.DataFrame(rows).sort_values("swing", ascending=False).reset_index(drop=True)
    return tornado


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--results-root", help="Folder containing base_scenario/ etc. (real baseline).")
    parser.add_argument("--variant", help="Results variant subfolder name.")
    parser.add_argument("--event-key", type=int, default=1, help="Event id for multihazard baseline.")
    parser.add_argument("--sample", action="store_true",
                        help="Force the illustrative sample baseline (skip loading real outputs).")
    parser.add_argument("--levels", type=int, default=5,
                        help="Number of multiplier steps per parameter (>=2).")
    parser.add_argument("--noise", type=float, default=0.0,
                        help="Std-dev of multiplicative Gaussian noise on perturbed costs (0 = off).")
    parser.add_argument("--seed", type=int, default=42, help="RNG seed for --noise.")
    parser.add_argument("--out-dir", default=None,
                        help="Directory for output CSVs (default: results/sensitivity_analysis/).")
    args = parser.parse_args()

    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)

    results_root = Path(args.results_root) if args.results_root else (REPO_ROOT / "results")
    baseline, source, unit_label = load_baseline_scenarios(
        results_root, args.variant, args.event_key, use_sample=args.sample
    )
    logging.info("Baseline source=%s | scenarios=%d | units=%s", source, len(baseline), unit_label)

    parameters = default_parameters()
    rng = np.random.default_rng(args.seed)
    oat = run_oat_sweep(baseline, parameters, n_levels=args.levels, noise=args.noise, rng=rng)
    tornado = build_tornado(oat, parameters)

    out_dir = Path(args.out_dir) if args.out_dir else (REPO_ROOT / "results" / "sensitivity_analysis")
    out_dir.mkdir(parents=True, exist_ok=True)
    oat_path = out_dir / "sensitivity_oat_results.csv"
    tornado_path = out_dir / "sensitivity_tornado.csv"
    baseline_path = out_dir / "sensitivity_baseline.csv"
    oat.to_csv(oat_path, index=False)
    tornado.to_csv(tornado_path, index=False)
    baseline.to_csv(baseline_path, index=False)

    print(f"\nSensitivity analysis | baseline={source} | units={unit_label}")
    print(f"Parameters swept: {len(parameters)} | levels/param: {args.levels} "
          f"| scenarios: {len(baseline)} | OAT rows: {len(oat)}")
    print("\nTornado (parameters ranked by combined-total swing across the sweep):")
    show = tornado.copy()
    for col in ("combined_total_low", "combined_total_base", "combined_total_high", "swing"):
        show[col] = show[col].round(3)
    show["swing_pct_of_base"] = show["swing_pct_of_base"].round(1)
    print(show[["parameter", "parameter_label", "combined_total_low",
                "combined_total_base", "combined_total_high", "swing",
                "swing_pct_of_base"]].to_string(index=False))

    print(f"\nWrote:\n  {oat_path}\n  {tornado_path}\n  {baseline_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
