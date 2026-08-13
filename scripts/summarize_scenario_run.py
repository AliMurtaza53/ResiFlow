#!/usr/bin/env python3
"""Print a compact scenario QA summary for pipeline results."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
VIZ_DIR = REPO_ROOT / "scripts" / "visualizations"
if str(VIZ_DIR) not in sys.path:
    sys.path.insert(0, str(VIZ_DIR))

from viz_data_loaders import (  # noqa: E402
    build_multihazard_summary_table,
    build_scenario_summary_table,
    is_testbed_variant,
    list_available_flood_keys,
    load_morris_sensitivity,
    plot_sensitivity_panels,
    validate_multihazard_summary,
)


def _first_existing(paths: list[Path]) -> Path | None:
    for path in paths:
        if path and path.exists():
            return path
    return None


def resolve_results_root(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    for key in ("RESIFLOW_RESULTS_ROOT", "NIRD_RESULTS_ROOT"):
        env = os.getenv(key)
        if env:
            return Path(env)
    for candidate in (
        REPO_ROOT / "results",
        REPO_ROOT / "sandbox" / "results",
        Path.home() / "NIRD_Data" / "results",
    ):
        if candidate.exists():
            return candidate
    raise FileNotFoundError("Could not locate results root. Set NIRD_RESULTS_ROOT.")


def resolve_variant(results_root: Path, explicit: str | None) -> str:
    if explicit:
        return explicit
    for key in ("RESIFLOW_RESULTS_VARIANT", "NIRD_RESULTS_VARIANT"):
        env = os.getenv(key)
        if env:
            return env
    base = results_root / "base_scenario"
    if base.exists():
        variants = sorted(p.name for p in base.iterdir() if p.is_dir())
        if variants:
            return variants[0]
    return "revision"


def _run_sensitivity(results_root: Path, variant: str, fig_out: str | None) -> int:
    """Render the Morris sensitivity panel from Script 5's morris_*.csv."""
    import matplotlib

    matplotlib.use("Agg")

    df = load_morris_sensitivity(results_root)
    if df.empty:
        print(
            f"No Morris sensitivity CSVs found under "
            f"{results_root / 'sensitivity_analysis'}.\n"
            "Run scripts/5_sensitivity_analysis_{direct,indirect}.py first "
            "(or scripts/testbed/run_sensitivity_sioux_falls.py for the testbed).",
            file=sys.stderr,
        )
        return 1

    print(f"Morris sensitivity | variant={variant} | targets={sorted(df['target'].unique())}")
    print(f"Results root: {results_root}\n")
    show_cols = [c for c in ("target", "Parameters", "S1_abs", "ST", "S1_abs_conf") if c in df.columns]
    print(df[show_cols].to_string(index=False))

    fig, _ = plot_sensitivity_panels(df, variant=variant)
    out_path = Path(fig_out) if fig_out else results_root / "figures" / "sensitivity_panel.png"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=200, bbox_inches="tight")
    print(f"\nWrote sensitivity panel: {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results-root", help="Folder containing base_scenario/ etc.")
    parser.add_argument("--variant", help="Results variant subfolder name")
    parser.add_argument("--depth-key", type=int, default=int(os.getenv("NIRD_DEPTH_KEY", "30")))
    parser.add_argument(
        "--flood-keys",
        help="Comma-separated flood event IDs (default: all available)",
    )
    parser.add_argument(
        "--multihazard",
        action="store_true",
        help="Summarize all registered multihazard scenarios (unique scenario_param per hazard)",
    )
    parser.add_argument("--event-key", type=int, default=1, help="Event id for multihazard mode")
    parser.add_argument(
        "--sensitivity",
        action="store_true",
        help="Render the Morris parameter-sensitivity panel from "
        "sensitivity_analysis/morris_{direct,indirect}.csv (Script 5 outputs)",
    )
    parser.add_argument(
        "--fig-out",
        help="Output path for the sensitivity figure "
        "(default: <results_root>/figures/sensitivity_panel.png)",
    )
    parser.add_argument(
        "--csv-out",
        help="Optional path to write the summary table as CSV",
    )
    args = parser.parse_args()

    results_root = resolve_results_root(args.results_root)
    variant = resolve_variant(results_root, args.variant)

    if args.sensitivity:
        return _run_sensitivity(results_root, variant, args.fig_out)

    if args.multihazard:
        summary = build_multihazard_summary_table(
            results_root,
            variant,
            event_key=int(args.event_key),
        )
        try:
            validate_multihazard_summary(summary, results_root=results_root, variant=variant)
        except FileNotFoundError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        label = f"Multihazard summary | variant={variant} | event={args.event_key}"
    else:
        flood_keys = None
        if args.flood_keys:
            flood_keys = [int(part.strip()) for part in args.flood_keys.split(",") if part.strip()]
        else:
            flood_keys = list_available_flood_keys(results_root, variant, args.depth_key)

        summary = build_scenario_summary_table(
            results_root,
            variant,
            args.depth_key,
            flood_keys=flood_keys or None,
        )
        label = f"Scenario QA summary | variant={variant} | depth={args.depth_key}"
    if summary.empty:
        print(
            f"No scenario outputs found under {results_root} "
            f"(variant={variant})."
        )
        return 1

    testbed = is_testbed_variant(variant)
    unit_hint = "KUSD (testbed)" if testbed else "MUSD (production-scale)"
    print(label + f" | units={unit_hint}")
    print(f"Results root: {results_root}")
    print("")

    display_cols = [
        "hazard_label",
        "scenario_param",
        "flood_key",
        "link_count",
        "flooded_links",
        "closed_links",
        "damaged_links",
        "freight_disrupted_flow",
        "passenger_disrupted_flow",
        "rerouting_cost_freight_display",
        "rerouting_cost_passenger_display",
        "direct_damage_display",
        "combined_total_display",
        "isolation_rows_freight",
        "isolation_rows_passenger",
        "isolation_flow_freight",
        "isolation_flow_passenger",
        "passenger_flooded_edge_flow",
    ]
    present = [col for col in display_cols if col in summary.columns]
    print(summary[present].to_string(index=False))

    if args.csv_out:
        out_path = Path(args.csv_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        summary.to_csv(out_path, index=False)
        print(f"\nWrote full summary: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
