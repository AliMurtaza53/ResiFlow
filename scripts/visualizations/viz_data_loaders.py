"""Shared loaders for recovery pipeline visualization notebooks."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import geopandas as gpd
import pandas as pd

DEFAULT_MAX_MAP_EDGES = int(os.getenv("NIRD_VIZ_MAX_MAP_EDGES", "50000"))
DEFAULT_MAP_EDGE_THRESHOLD = int(os.getenv("NIRD_VIZ_MAP_EDGE_THRESHOLD", "100000"))
VIZ_SAMPLE_STRIDE = int(os.getenv("NIRD_VIZ_SAMPLE_STRIDE", "1"))

CostDisplayUnit = Literal["auto", "usd", "kusd", "musd", "busd"]
ResolvedCostUnit = Literal["usd", "kusd", "musd", "busd"]

SCTG_G5_LABELS: dict[str, str] = {
    "sctg0109": "SCTG 01-09: Ag, fish, forestry",
    "sctg1014": "SCTG 10-14: Mining",
    "sctg1519": "SCTG 15-19: Petroleum & coal",
    "sctg2033": "SCTG 20-33: Manufactured goods",
    "sctg3499": "SCTG 34-99: Mixed & other",
}


def resolve_input_od_matrix_path(input_root: Path) -> Path:
    candidates = [
        input_root / "census_datasets" / "faf5_od_matrix.pq",
        input_root / "inputs" / "census_datasets" / "faf5_od_matrix.pq",
    ]
    env_path = os.getenv("RESIFLOW_FAF5_OD_MATRIX_PATH") or os.getenv("NIRD_FAF5_OD_MATRIX_PATH")
    if env_path:
        candidates.insert(0, Path(env_path))
    for path in candidates:
        if path.exists():
            return path
    raise FileNotFoundError(f"Could not locate faf5_od_matrix.pq under {input_root}")


def resolve_sctg_summary_path(input_root: Path) -> Path:
    path = input_root / "census_datasets" / "faf5_sctg_daily_trucks.pq"
    if path.exists():
        return path
    raise FileNotFoundError(
        f"Missing {path}. Run scripts/build_faf5_sctg_summary.py after installing county OD."
    )


def load_assignment_od_demand(input_root: Path) -> tuple[pd.DataFrame, Path]:
    """Load the full Script 1 demand table (daily truck trips)."""
    path = resolve_input_od_matrix_path(input_root)
    df = pd.read_parquet(path)
    flow_col = _flow_column(df)
    out = df.copy()
    if flow_col != "flow":
        out["flow"] = pd.to_numeric(out[flow_col], errors="coerce").fillna(0.0)
    return out, path


def load_sctg_summary(input_root: Path) -> tuple[pd.DataFrame, Path]:
    path = resolve_sctg_summary_path(input_root)
    return pd.read_parquet(path), path


def prepare_damage_for_viz(damage_df: pd.DataFrame) -> pd.DataFrame:
    """Attach consolidated USD damage columns for plotting."""
    from resiflow.damage_aggregation import add_consolidated_damage_columns

    if "direct_damage_mean_usd" in damage_df.columns:
        out = damage_df.copy()
    else:
        out = add_consolidated_damage_columns(damage_df)
    out["total_damage_value_usd"] = pd.to_numeric(
        out["direct_damage_mean_usd"], errors="coerce"
    ).fillna(0.0)
    return out


def event_damage_total_usd(damage_df: pd.DataFrame) -> float:
    from resiflow.damage_aggregation import total_direct_damage_usd

    if "direct_damage_mean_usd" in damage_df.columns:
        return float(pd.to_numeric(damage_df["direct_damage_mean_usd"], errors="coerce").fillna(0).sum())
    return total_direct_damage_usd(damage_df)


def is_testbed_variant(variant: str | None) -> bool:
    """Return True for toy / Sioux Falls style variants used in pytest fixtures."""
    if os.getenv("NIRD_TESTBED", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if not variant:
        return False
    lower = variant.lower()
    return lower.startswith("toy_") or "sioux_falls" in lower


def resolve_cost_display_unit(
    value_usd: float,
    *,
    unit: CostDisplayUnit = "auto",
    variant: str | None = None,
) -> ResolvedCostUnit:
    """Pick a human-readable cost unit (KUSD for testbeds, MUSD for production-scale)."""
    explicit = (unit if unit != "auto" else os.getenv("NIRD_COST_DISPLAY_UNIT", "auto")).strip().lower()
    if explicit in {"usd", "kusd", "musd", "busd"}:
        return explicit  # type: ignore[return-value]

    abs_value = abs(float(value_usd))
    if is_testbed_variant(variant):
        if abs_value < 1_000_000:
            return "kusd"
        if abs_value < 1_000_000_000:
            return "musd"
        return "busd"

    if abs_value < 1_000_000:
        return "kusd"
    if abs_value < 1_000_000_000:
        return "musd"
    return "busd"


def format_cost(
    value_usd: float,
    *,
    unit: CostDisplayUnit = "auto",
    variant: str | None = None,
) -> str:
    """Format a USD amount using KUSD/MUSD/BUSD depending on scale and testbed mode."""
    resolved = resolve_cost_display_unit(value_usd, unit=unit, variant=variant)
    value = float(value_usd)
    if resolved == "kusd":
        return f"${value / 1_000:,.1f}K"
    if resolved == "musd":
        return f"${value / 1_000_000:,.2f}M"
    if resolved == "busd":
        return f"${value / 1_000_000_000:,.2f}B"
    return f"${value:,.2f}"


def format_usd_millions(value_usd: float) -> str:
    """Backward-compatible wrapper; prefer :func:`format_cost`."""
    return format_cost(value_usd, unit="auto")


def _numeric_series(df: pd.DataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in df.columns:
        return pd.Series(dtype=float)
    return pd.to_numeric(df[column], errors="coerce").fillna(default)


def _first_cost_row(cost_path: Path) -> dict[str, float]:
    if not cost_path.exists():
        return {}
    costs = pd.read_csv(cost_path)
    if costs.empty:
        return {}
    row = costs.iloc[0]
    out: dict[str, float] = {}
    for column in (
        "total_disrupted_flow",
        "total_disrupted_flow_unique_od",
        "rerouting_cost",
        "rer_time",
        "rer_operate",
        "rer_toll",
        "direct_damage_total",
        "direct_damage_total_usd",
        "combined_total_cost",
    ):
        if column in row.index:
            out[column] = float(pd.to_numeric(row[column], errors="coerce"))
    return out


def _direct_damage_usd_from_cost_row(row: dict[str, float], damage_df: pd.DataFrame | None) -> float:
    if "direct_damage_total_usd" in row:
        return float(row["direct_damage_total_usd"])
    if "direct_damage_total" in row:
        return float(row["direct_damage_total"])
    if damage_df is not None and not damage_df.empty:
        return event_damage_total_usd(damage_df)
    return 0.0


def _intensity_depth_m(links: pd.DataFrame) -> pd.Series:
    """Primary hazard intensity in meters (flood depth or snow mm converted)."""
    from resiflow.disruption.link_record import intensity_series

    hazard = None
    if "hazard_type" in links.columns and links["hazard_type"].notna().any():
        hazard = str(links["hazard_type"].dropna().iloc[0])
    return intensity_series(links, hazard_type=hazard)


def _disruption_link_metrics(links: pd.DataFrame) -> dict[str, int | float]:
    intensity_m = _intensity_depth_m(links)
    flood_depth = _numeric_series(links, "flood_depth_max")
    if intensity_m.sum() > 0 and flood_depth.sum() == 0:
        flood_depth = intensity_m
    max_speed = _numeric_series(links, "max_speed", default=999.0)
    damage_level = links.get("damage_level_max", pd.Series(dtype=object)).astype(str).str.lower()
    flooded = int((flood_depth > 0).sum())
    closed = int((max_speed == 0).sum())
    damaged = int(damage_level.isin({"minor", "moderate", "extensive", "severe"}).sum())
    return {
        "link_count": int(len(links)),
        "flooded_links": flooded,
        "closed_links": closed,
        "damaged_links": damaged,
        "max_flood_depth_m": float(flood_depth.max()) if len(flood_depth) else 0.0,
    }


def _isolation_metrics(reroute_dir: Path, scenario_id: int = 1) -> dict[str, float | int]:
    out: dict[str, float | int] = {
        "isolation_rows": 0,
        "isolation_flow": 0.0,
        "isolation_rows_freight": 0,
        "isolation_flow_freight": 0.0,
        "isolation_rows_passenger": 0,
        "isolation_flow_passenger": 0.0,
    }
    for mode, stem in (
        ("freight", f"trip_isolations_freight_s{scenario_id}_day1"),
        ("passenger", f"trip_isolations_passenger_s{scenario_id}_day1"),
    ):
        csv_path = reroute_dir / f"{stem}.csv"
        if not csv_path.exists():
            continue
        iso = pd.read_csv(csv_path)
        flow_col = "Car21" if "Car21" in iso.columns else "flow"
        flows = _numeric_series(iso, flow_col) if flow_col in iso.columns else pd.Series(dtype=float)
        out[f"isolation_rows_{mode}"] = int(len(iso))
        out[f"isolation_flow_{mode}"] = float(flows.sum()) if len(flows) else 0.0
    out["isolation_rows"] = int(out["isolation_rows_freight"] + out["isolation_rows_passenger"])
    out["isolation_flow"] = float(out["isolation_flow_freight"] + out["isolation_flow_passenger"])
    return out


def _scenario_artifact_paths(
    results_root: Path,
    *,
    variant: str,
    depth_key: int,
    flood_key: int,
) -> dict[str, Path]:
    """Canonical pipeline artifacts for one scenario (unique scenario_param paths)."""
    disruption_links = (
        results_root
        / "disruption_analysis"
        / variant
        / str(depth_key)
        / "links"
        / f"road_links_{flood_key}.gpq"
    )
    damage_primary = (
        results_root
        / "damage_analysis"
        / variant
        / str(depth_key)
        / f"intersections_{flood_key}_with_damage_values.csv"
    )
    damage_legacy = (
        results_root
        / "damage_analysis"
        / variant
        / f"intersections_{flood_key}_with_damage_values.csv"
    )
    reroute_dir = results_root / "rerouting_analysis" / variant / str(depth_key) / str(flood_key)
    return {
        "disruption_links": disruption_links,
        "damage_csv": damage_primary if damage_primary.exists() else damage_legacy,
        "freight_cost": reroute_dir / "cost_matrix_by_scenario.csv",
        "passenger_cost": reroute_dir / "cost_matrix_passenger_by_scenario.csv",
    }


def scenario_outputs_present(
    results_root: Path,
    *,
    variant: str,
    depth_key: int,
    flood_key: int,
) -> tuple[bool, list[str]]:
    """True when disruption links or reroute cost matrices exist on disk."""
    paths = _scenario_artifact_paths(
        results_root,
        variant=variant,
        depth_key=depth_key,
        flood_key=flood_key,
    )
    missing = [name for name, path in paths.items() if not path.exists()]
    has_data = paths["disruption_links"].exists() or paths["freight_cost"].exists()
    return has_data, missing


def summarize_single_scenario(
    results_root: Path,
    *,
    variant: str,
    depth_key: int,
    flood_key: int,
    recovery_scenario: int = 1,
    recovery_day: int = 1,
) -> dict[str, float | int | str]:
    """Collect headline QA metrics for one hazard scenario."""
    artifacts = _scenario_artifact_paths(
        results_root,
        variant=variant,
        depth_key=depth_key,
        flood_key=flood_key,
    )
    has_data, missing = scenario_outputs_present(
        results_root,
        variant=variant,
        depth_key=depth_key,
        flood_key=flood_key,
    )
    disruption_links_path = artifacts["disruption_links"]
    damage_path = artifacts["damage_csv"]
    freight_cost_path = artifacts["freight_cost"]
    passenger_cost_path = artifacts["passenger_cost"]
    reroute_dir = freight_cost_path.parent

    links = pd.read_parquet(disruption_links_path) if disruption_links_path.exists() else pd.DataFrame()
    damage_df = pd.read_csv(damage_path) if damage_path.exists() else pd.DataFrame()
    link_metrics = _disruption_link_metrics(links) if not links.empty else {
        "link_count": 0,
        "flooded_links": 0,
        "closed_links": 0,
        "damaged_links": 0,
        "max_flood_depth_m": 0.0,
    }

    freight_row = _first_cost_row(freight_cost_path)
    passenger_row = _first_cost_row(passenger_cost_path)
    freight_disrupted = float(
        freight_row.get(
            "total_disrupted_flow_unique_od",
            freight_row.get("total_disrupted_flow", 0.0),
        )
    )
    passenger_disrupted = float(
        passenger_row.get(
            "total_disrupted_flow_unique_od",
            passenger_row.get("total_disrupted_flow", 0.0),
        )
    )
    direct_damage_usd = _direct_damage_usd_from_cost_row(freight_row, damage_df)
    rerouting_freight = float(freight_row.get("rerouting_cost", 0.0))
    rerouting_passenger = float(passenger_row.get("rerouting_cost", 0.0))
    combined_total = float(
        freight_row.get("combined_total_cost", direct_damage_usd + rerouting_freight)
    )
    isolation = _isolation_metrics(reroute_dir, scenario_id=recovery_scenario)

    passenger_post = reroute_dir / f"edge_flows_passenger_s{recovery_scenario}_day{recovery_day}.gpq"
    flooded_flow_delta = 0.0
    if passenger_post.exists():
        post = pd.read_parquet(passenger_post)
        flow_col = next((c for c in ("acc_flow", "flow") if c in post.columns), None)
        flood_depth = _intensity_depth_m(links) if not links.empty else pd.Series(dtype=float)
        if flow_col and not links.empty and "e_id" in post.columns:
            flooded_ids = links.loc[flood_depth > 0, "e_id"].astype(str)
            flooded_flow_delta = float(
                _numeric_series(post, flow_col)
                .loc[post["e_id"].astype(str).isin(flooded_ids)]
                .sum()
            )

    row: dict[str, float | int | str] = {
        "variant": variant,
        "depth_key": int(depth_key),
        "flood_key": int(flood_key),
        **link_metrics,
        "freight_disrupted_flow": freight_disrupted,
        "passenger_disrupted_flow": passenger_disrupted,
        "freight_disrupted_flow_raw": float(freight_row.get("total_disrupted_flow", 0.0)),
        "passenger_disrupted_flow_raw": float(passenger_row.get("total_disrupted_flow", 0.0)),
        "rerouting_cost_freight_usd": rerouting_freight,
        "rerouting_cost_passenger_usd": rerouting_passenger,
        "direct_damage_usd": direct_damage_usd,
        "combined_total_usd": combined_total,
        "passenger_flooded_edge_flow": flooded_flow_delta,
        **isolation,
        "data_present": has_data,
        "missing_outputs": ",".join(missing),
    }
    row["direct_damage_display"] = format_cost(direct_damage_usd, variant=variant)
    row["rerouting_cost_freight_display"] = format_cost(rerouting_freight, variant=variant)
    row["rerouting_cost_passenger_display"] = format_cost(rerouting_passenger, variant=variant)
    row["combined_total_display"] = format_cost(combined_total, variant=variant)
    return row


def list_available_flood_keys(results_root: Path, variant: str, depth_key: int) -> list[int]:
    links_dir = results_root / "disruption_analysis" / variant / str(depth_key) / "links"
    if not links_dir.exists():
        return []
    flood_ids: list[int] = []
    for path in links_dir.glob("road_links_*.gpq"):
        tail = path.stem.split("_")[-1]
        if tail.isdigit():
            flood_ids.append(int(tail))
    return sorted(set(flood_ids))


def list_available_scenario_params(results_root: Path, variant: str) -> list[int]:
    """List scenario_param folders under disruption_analysis for a variant."""
    disrupt_root = results_root / "disruption_analysis" / variant
    if not disrupt_root.exists():
        return []
    params: list[int] = []
    for path in disrupt_root.iterdir():
        if path.is_dir() and path.name.isdigit():
            params.append(int(path.name))
    return sorted(params)


def build_scenario_summary_table(
    results_root: Path,
    variant: str,
    depth_key: int,
    flood_keys: list[int] | None = None,
) -> pd.DataFrame:
    """Build one QA summary row per flood scenario under a variant/depth."""
    keys = flood_keys or list_available_flood_keys(results_root, variant, depth_key)
    if not keys:
        return pd.DataFrame()
    rows = [
        summarize_single_scenario(
            results_root,
            variant=variant,
            depth_key=depth_key,
            flood_key=flood_key,
        )
        for flood_key in keys
    ]
    return pd.DataFrame(rows)


MULTIHAZARD_PANEL_ORDER: tuple[tuple[str, str | None, str], ...] = (
    ("flood", "flood_surface", "Flood surface"),
    ("flood", "flood_river", "Flood river"),
    ("flood", "flood_coastal", "Flood coastal"),
    ("earthquake", None, "Earthquake"),
    ("landslide", None, "Landslide"),
    ("winter_storm", None, "Winter storm"),
)


def build_multihazard_summary_table(
    results_root: Path,
    variant: str,
    *,
    event_key: int = 1,
    scenario_specs: tuple[tuple[str, str | None, str], ...] | None = None,
) -> pd.DataFrame:
    """One row per registered multihazard scenario (unique scenario_param paths)."""
    from resiflow.hazards.scenario_registry import HazardScenario, lookup_scenario_by_env

    specs = scenario_specs or MULTIHAZARD_PANEL_ORDER
    rows: list[dict[str, float | int | str]] = []
    env_backup = {
        "RESIFLOW_HAZARD_TYPE": os.environ.get("RESIFLOW_HAZARD_TYPE"),
        "RESIFLOW_FLOOD_SUBTYPE": os.environ.get("RESIFLOW_FLOOD_SUBTYPE"),
    }
    try:
        for hazard_type, flood_subtype, label in specs:
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

            scenario: HazardScenario | None = lookup_scenario_by_env()
            if scenario is None:
                continue
            row = summarize_single_scenario(
                results_root,
                variant=variant,
                depth_key=int(scenario.scenario_param),
                flood_key=int(event_key),
            )
            row["hazard_type"] = hazard_type
            row["hazard_subtype"] = flood_subtype or ""
            row["hazard_label"] = label
            row["scenario_param"] = int(scenario.scenario_param)
            row["panel_row"] = "floods" if hazard_type == "flood" else "other"
            rows.append(row)
    finally:
        for key, value in env_backup.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def validate_multihazard_summary(
    summary: pd.DataFrame,
    *,
    results_root: Path,
    variant: str,
) -> int:
    """Return count of scenarios with on-disk outputs; raise if none found."""
    if summary.empty:
        raise FileNotFoundError(
            f"No multihazard scenarios resolved for variant={variant} under {results_root}."
        )
    if "data_present" not in summary.columns:
        return len(summary)

    present = int(summary["data_present"].fillna(False).astype(bool).sum())
    if present == 0:
        raise FileNotFoundError(
            f"No pipeline outputs found under {results_root} for variant={variant}.\n"
            "Generate them first:\n"
            "  python scripts/testbed/run_multihazard_sioux_falls.py\n"
            "(default output: results/multihazard_panel/)\n"
            "Avoid storing panel results under .pytest-tmp/ — pytest deletes that folder "
            "when run with --basetemp .pytest-tmp."
        )

    missing_labels = summary.loc[~summary["data_present"].fillna(False), "hazard_label"].tolist()
    if missing_labels:
        import warnings

        warnings.warn(
            f"Partial multihazard outputs: missing data for {missing_labels}. "
            "Re-run run_multihazard_sioux_falls.py or check scenario_param folders.",
            stacklevel=2,
        )
    return present


# Categorical palette: colorblind-safe 8-hue set (OKLab-validated adjacent
# pairs, worst-case CVD dE 9.1 light/8.4 dark) -- see the dataviz skill's
# references/palette.md. Slots 1-4 used here in documented default order;
# extend with slot 5+ (magenta) only if a 5th hazard is ever added, and
# re-check the adjacent-pair guarantee still holds for that count.
HAZARD_PALETTE: dict[str, str] = {
    "flood_surface": "#2a78d6",  # slot 1: blue
    "flood_river": "#2a78d6",
    "flood_coastal": "#2a78d6",
    "earthquake": "#eb6834",  # slot 2: orange
    "landslide": "#1baf7a",  # slot 3: aqua
    "winter_storm": "#eda100",  # slot 4: yellow
}
_INK_PRIMARY = "#0b0b0b"
_INK_SECONDARY = "#52514e"
_INK_MUTED = "#898781"
_GRIDLINE = "#e1e0d9"
_SURFACE = "#fcfcfb"


def _hazard_color(hazard_type: str, hazard_subtype: str = "") -> str:
    key = hazard_subtype or hazard_type
    return HAZARD_PALETTE.get(str(key).lower(), _INK_MUTED)


def _style_axis(ax) -> None:
    ax.set_facecolor(_SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(_INK_MUTED)
        ax.spines[side].set_linewidth(0.8)
    ax.yaxis.grid(True, color=_GRIDLINE, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(colors=_INK_SECONDARY, labelsize=9)
    ax.xaxis.label.set_color(_INK_SECONDARY)
    ax.yaxis.label.set_color(_INK_SECONDARY)


def plot_multihazard_cost_panels(
    summary: pd.DataFrame,
    *,
    variant: str | None = None,
    direct_cost_caveat: str | None = (
        "Direct costs: illustrative placeholder pending HAZUS-sourced "
        "unit-repair-cost tables"
    ),
):
    """Two-panel comparison: direct vs. indirect cost, and freight vs.
    passenger indirect cost, both by hazard type.

    Panel A answers "how do direct and indirect costs compare?" -- for each
    hazard, a solid bar (direct) beside a hatched bar (indirect, freight +
    passenger combined). Panel B answers "how does indirect cost split by
    mode?" -- for each hazard, solid (freight) beside hatched (passenger).
    Color encodes hazard identity consistently across both panels (the
    dimension a reader tracks across the whole figure); the solid/hatched
    texture is the secondary channel distinguishing the two bars within each
    hazard, so the split reads without relying on hue alone.

    ``direct_cost_caveat`` renders as a figure-level footnote -- pass None
    once direct costs are backed by real hazard-specific unit-cost tables.
    """
    import matplotlib.pyplot as plt
    import numpy as np

    if summary.empty:
        raise ValueError("multihazard summary is empty")

    resolved_variant = variant or (
        str(summary["variant"].iloc[0]) if "variant" in summary.columns else ""
    )
    df = summary.reset_index(drop=True)
    labels = df["hazard_label"].astype(str).tolist()
    colors = [
        _hazard_color(row.get("hazard_type", ""), row.get("hazard_subtype", ""))
        for _, row in df.iterrows()
    ]
    direct = pd.to_numeric(df["direct_damage_usd"], errors="coerce").fillna(0.0)
    freight = pd.to_numeric(df["rerouting_cost_freight_usd"], errors="coerce").fillna(0.0)
    passenger = pd.to_numeric(df["rerouting_cost_passenger_usd"], errors="coerce").fillna(0.0)
    indirect_total = freight + passenger

    max_abs = float(pd.concat([direct, indirect_total, freight, passenger]).abs().max() or 0.0)
    unit = resolve_cost_display_unit(max_abs, variant=resolved_variant)
    divisor = {"usd": 1.0, "kusd": 1e3, "musd": 1e6, "busd": 1e9}[unit]
    unit_label = {"usd": "USD", "kusd": "USD (thousands)", "musd": "USD (millions)", "busd": "USD (billions)"}[unit]

    plt.rcParams["font.family"] = "sans-serif"
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(12, 5), facecolor=_SURFACE)
    x = np.arange(len(labels))
    bar_w = 0.36

    def _paired_bars(ax, solid_vals, hatched_vals, solid_label, hatched_label):
        ax.bar(
            x - bar_w / 2, solid_vals / divisor, bar_w,
            color=colors, edgecolor=_INK_PRIMARY, linewidth=0.6, zorder=2,
        )
        ax.bar(
            x + bar_w / 2, hatched_vals / divisor, bar_w,
            color=colors, edgecolor=_INK_PRIMARY, linewidth=0.6,
            hatch="////", alpha=0.55, zorder=2,
        )
        for xi, v in zip(x - bar_w / 2, solid_vals / divisor):
            ax.annotate(f"{v:,.1f}", (xi, v), xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=7.5, color=_INK_SECONDARY)
        for xi, v in zip(x + bar_w / 2, hatched_vals / divisor):
            ax.annotate(f"{v:,.1f}", (xi, v), xytext=(0, 3), textcoords="offset points",
                        ha="center", va="bottom", fontsize=7.5, color=_INK_SECONDARY)
        ax.set_xticks(x)
        ax.set_xticklabels(labels, rotation=15, ha="right")
        ymin, ymax = ax.get_ylim()
        ax.set_ylim(ymin, ymax * 1.22)  # headroom so the legend clears the tallest bar/label
        _style_axis(ax)
        from matplotlib.patches import Patch
        legend_handles = [
            Patch(facecolor=_INK_MUTED, edgecolor=_INK_PRIMARY, linewidth=0.6, label=solid_label),
            Patch(facecolor=_INK_MUTED, edgecolor=_INK_PRIMARY, linewidth=0.6,
                  hatch="////", alpha=0.55, label=hatched_label),
        ]
        ax.legend(handles=legend_handles, loc="upper right", fontsize=8.5, frameon=False)

    _paired_bars(ax_a, direct, indirect_total, "Direct", "Indirect (freight + passenger)")
    ax_a.set_title("Direct vs. indirect cost", fontsize=12, color=_INK_PRIMARY, loc="left")
    ax_a.set_ylabel(unit_label, fontsize=9.5)

    _paired_bars(ax_b, freight, passenger, "Freight", "Passenger")
    ax_b.set_title("Indirect cost by mode", fontsize=12, color=_INK_PRIMARY, loc="left")
    ax_b.set_ylabel(unit_label, fontsize=9.5)

    fig.suptitle("Multi-hazard cost comparison", fontsize=14, color=_INK_PRIMARY, y=1.02)
    if direct_cost_caveat:
        fig.text(0.01, -0.02, f"* {direct_cost_caveat}", fontsize=8, color=_INK_MUTED, ha="left")
    fig.tight_layout()
    return fig, (ax_a, ax_b)


def resolve_county_od_path(input_root: Path) -> Path | None:
    """Optional county-level OD with commodity columns (sctgG5 / daily_truck_trips)."""
    from resiflow.faf5_paths import resolve_detailed_county_od_path, resolve_faf5_data_root

    repo_root = Path(__file__).resolve().parents[2]
    faf5_root = resolve_faf5_data_root(input_root, repo_root)
    return resolve_detailed_county_od_path(faf5_root, input_root)


def _flow_column(df: pd.DataFrame) -> str:
    for col in ("Car21", "flow", "daily_truck_trips", "daily_trips"):
        if col in df.columns:
            return col
    raise ValueError(f"No flow column found in {list(df.columns)}")


def summarize_od_flows(df: pd.DataFrame, label: str) -> dict[str, float | int | str]:
    flow_col = _flow_column(df)
    flows = pd.to_numeric(df[flow_col], errors="coerce").fillna(0.0)
    return {
        "label": label,
        "rows": int(len(df)),
        "flow_column": flow_col,
        "total_daily_trucks": float(flows.sum()),
        "max_daily_trucks": float(flows.max()) if len(flows) else 0.0,
        "median_daily_trucks": float(flows.median()) if len(flows) else 0.0,
        "p99_daily_trucks": float(flows.quantile(0.99)) if len(flows) else 0.0,
    }


def build_flow_validation_table(
    input_root: Path,
    variant_root: Path,
    *,
    viz_stride: int | None = None,
) -> pd.DataFrame:
    """Compare full assignment OD, optional viz sidecar sample, and edge-flow totals."""
    stride = VIZ_SAMPLE_STRIDE if viz_stride is None else viz_stride
    rows: list[dict[str, float | int | str]] = []

    od_path = resolve_input_od_matrix_path(input_root)
    full_od = pd.read_parquet(od_path)
    rows.append(summarize_od_flows(full_od, "Full assignment OD (faf5_od_matrix)"))
    if stride > 1:
        rows.append(
            summarize_od_flows(
                full_od.iloc[::stride].copy(),
                f"Stride-{stride} sample (dev only)",
            )
        )

    try:
        assigned, assigned_source = load_odpfc(variant_root)
        full_total = float(rows[0]["total_daily_trucks"]) if rows else 0.0
        assigned_total = float(
            pd.to_numeric(assigned.get("flow", assigned.get("Car21", 0)), errors="coerce")
            .fillna(0.0)
            .sum()
        )
        # Ignore stale partial odpfc sidecars that are not representative of full assignment.
        if full_total <= 0 or assigned_total >= 0.5 * full_total:
            rows.append(
                summarize_od_flows(
                    assigned,
                    f"Assigned OD paths ({assigned_source.name})",
                )
            )
    except FileNotFoundError:
        pass

    edge_flows, edge_source = load_edge_flows(variant_root)
    edge_col = next(
        (c for c in ("acc_flow", "flow", "Car21", "current_flow") if c in edge_flows.columns),
        None,
    )
    if edge_col:
        edge_vals = pd.to_numeric(edge_flows[edge_col], errors="coerce").fillna(0.0)
        rows.append(
            {
                "label": f"Link flows ({edge_source.name})",
                "rows": int(len(edge_flows)),
                "flow_column": edge_col,
                "total_daily_trucks": float(edge_vals.sum()),
                "max_daily_trucks": float(edge_vals.max()),
                "median_daily_trucks": float(edge_vals.median()),
                "p99_daily_trucks": float(edge_vals.quantile(0.99)),
            }
        )

    out = pd.DataFrame(rows)
    out["note"] = (
        "Car21 / flow = daily truck trips from FAF5 county disaggregation "
        "(annual_tons / payload / 365). Link-flow totals sum across links and "
        "are not comparable to OD-trip totals."
    )
    return out


def load_county_od_by_sctg(input_root: Path) -> tuple[pd.DataFrame, Path]:
    county_path = resolve_county_od_path(input_root)
    if county_path is None:
        raise FileNotFoundError(
            "County-level FAF5 OD with commodity not found. Set NIRD_FAF5_COUNTY_OD_PATH "
            "to a parquet/CSV containing sctgG5 and daily_truck_trips or tons."
        )
    if county_path.suffix.lower() in {".pq", ".parquet"}:
        df = pd.read_parquet(county_path)
    else:
        df = pd.read_csv(county_path)
    if "sctgG5" not in df.columns:
        from resiflow.faf5_county_disaggregation import map_faf_sctg_to_sctgG5

        working = df.copy()
        if "sctg" not in working.columns and "sctg2" in working.columns:
            working = working.rename(columns={"sctg2": "sctg"})
        df = map_faf_sctg_to_sctgG5(working)
    if "sctgG5" not in df.columns:
        raise ValueError(f"{county_path} does not contain sctgG5 or sctg2")
    return df, county_path


def aggregate_sctg_daily_trucks(county_od: pd.DataFrame) -> pd.DataFrame:
    flow_col = _flow_column(county_od)
    grouped = (
        county_od.assign(
            sctgG5=county_od["sctgG5"].astype(str),
            flow=pd.to_numeric(county_od[flow_col], errors="coerce").fillna(0.0),
        )
        .groupby("sctgG5", as_index=False)["flow"]
        .sum()
        .sort_values("flow", ascending=False)
    )
    grouped["industry"] = grouped["sctgG5"].map(SCTG_G5_LABELS).fillna(grouped["sctgG5"])
    grouped["share_pct"] = grouped["flow"] / grouped["flow"].sum() * 100.0
    return grouped.rename(columns={"flow": "daily_truck_trips"})


def should_skip_map_layers(links_gdf: gpd.GeoDataFrame | pd.DataFrame) -> bool:
    """Skip choropleth/line maps when link counts exceed safe notebook limits."""
    if os.getenv("NIRD_VIZ_SKIP_MAPS", "0").strip().lower() in {"1", "true", "yes"}:
        return True
    return len(links_gdf) > DEFAULT_MAP_EDGE_THRESHOLD


def resolve_odpfc_path(variant_root: Path) -> Path | None:
    """Return combined odpfc.pq or the first available odpfc_parts parquet."""
    combined = variant_root / "odpfc.pq"
    if combined.exists():
        return combined
    parts_dir = variant_root / "odpfc_parts"
    if parts_dir.is_dir():
        parts = sorted(parts_dir.glob("*.pq"))
        if parts:
            return parts[0] if len(parts) == 1 else parts_dir
    return None


def load_odpfc(variant_root: Path) -> tuple[pd.DataFrame, Path]:
    """Load baseline OD path table from odpfc.pq or odpfc_parts/*.pq."""
    combined = variant_root / "odpfc.pq"
    if combined.exists():
        return pd.read_parquet(combined), combined

    parts_dir = variant_root / "odpfc_parts"
    parts = sorted(parts_dir.glob("*.pq")) if parts_dir.is_dir() else []
    if not parts:
        raise FileNotFoundError(
            f"Missing odpfc.pq and odpfc_parts under {variant_root}. "
            "Run the viz ODPFC sidecar with NIRD_COMBINE_ODPFC_PARTS=1."
        )

    frames = [pd.read_parquet(part) for part in parts]
    merged = pd.concat(frames, ignore_index=True)
    return merged, parts_dir


def resolve_edge_flows_path(variant_root: Path) -> Path:
    """Prefer Pass A edge flows backup for baseline Step 1 panels when present."""
    pass_a = variant_root / "edge_flows_pass_a.gpq"
    if pass_a.exists():
        return pass_a
    current = variant_root / "edge_flows.gpq"
    if current.exists():
        return current
    raise FileNotFoundError(f"Missing edge flows under {variant_root}")


def load_edge_flows(variant_root: Path) -> tuple[gpd.GeoDataFrame, Path]:
    path = resolve_edge_flows_path(variant_root)
    return gpd.read_parquet(path), path


def subset_links_for_map(
    links_gdf: gpd.GeoDataFrame,
    flow_col: str = "acc_flow",
    *,
    max_edges: int | None = None,
    min_flow: float = 0.0,
) -> gpd.GeoDataFrame:
    """Keep high-flow links only so CONUS maps stay within notebook memory limits."""
    limit = DEFAULT_MAX_MAP_EDGES if max_edges is None else max_edges
    if limit <= 0 or len(links_gdf) <= limit:
        return links_gdf

    flow_candidates = [flow_col, "flow", "current_flow", "acc_flow"]
    col = next((c for c in flow_candidates if c in links_gdf.columns), None)
    if col is None:
        return links_gdf.iloc[:limit].copy()

    flows = pd.to_numeric(links_gdf[col], errors="coerce").fillna(0.0)
    active = links_gdf.loc[flows > min_flow].copy()
    if len(active) <= limit:
        return active
    return active.assign(_viz_flow=flows.loc[active.index]).nlargest(limit, "_viz_flow").drop(
        columns="_viz_flow"
    )
