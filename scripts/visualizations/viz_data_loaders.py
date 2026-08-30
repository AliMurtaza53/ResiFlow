"""Shared loaders for recovery pipeline visualization notebooks."""

from __future__ import annotations

import json
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
    isolation_cost_freight_usd = float(freight_row.get("isolation_cost", 0.0))
    isolation_cost_passenger_usd = float(passenger_row.get("isolation_cost", 0.0))
    isolation_cost_usd = isolation_cost_freight_usd + isolation_cost_passenger_usd
    combined_total = float(
        freight_row.get(
            "combined_total_cost",
            direct_damage_usd + rerouting_freight + isolation_cost_freight_usd,
        )
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
        "isolation_cost_freight_usd": isolation_cost_freight_usd,
        "isolation_cost_passenger_usd": isolation_cost_passenger_usd,
        "isolation_cost_usd": isolation_cost_usd,
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
# Urban Institute Data Visualization Style Guide palette
# (urbaninstitute.github.io/graphics-styleguide): cyan/gray/black primary,
# yellow/magenta secondary, green/red tertiary. Harvey gets Urban's dark-cyan
# shade rather than a new hue -- it's still hazard_type=="flood", just a
# distinct scenario, so a shade-within-family reads as "related to flood,
# not a fifth category" rather than introducing an unrelated color.
HAZARD_PALETTE: dict[str, str] = {
    "flood": "#1696D2",  # Urban cyan (core)
    "flood_surface": "#1696D2",
    "flood_river": "#1696D2",
    "flood_coastal": "#1696D2",
    "flood_harvey_houston": "#0A4C6A",  # Urban cyan (dark shade)
    "earthquake": "#EC008B",  # Urban magenta (core)
    "landslide": "#55B748",  # Urban green (core)
    "winter_storm": "#FDBF11",  # Urban yellow (core)
}
_INK_PRIMARY = "#000000"
_INK_SECONDARY = "#5c5859"
_INK_MUTED = "#a6a6a6"
_GRIDLINE = "#ececec"
_SURFACE = "#ffffff"
_FONT_FAMILY = ["Lato", "Arial", "sans-serif"]

# Urban Institute type scale (guide gives PDF pt / web px per element; these
# are matplotlib point sizes tuned for on-screen PNG viewing, i.e. scaled
# toward the guide's web column rather than its print column, since these
# figures are viewed directly, not placed in a print layout). Applied via
# these constants -- not per-chart guesses -- so every chart in this module
# shares one deliberate hierarchy: title > subtitle > legend > axis label >
# tick/data label > source note.
_FS_TITLE = 17.5
_FS_SUBTITLE = 12.5
_FS_LEGEND = 11
_FS_AXIS_LABEL = 11.5
_FS_TICK = 11
_FS_DATA_LABEL = 10
_FS_SOURCE = 9.5


def _hazard_color(hazard_type: str, hazard_subtype: str = "") -> str:
    """Color by hazard TYPE identity (the bounded, 4-way categorical dimension) --
    never a per-subtype hue. Subtypes (earthquake_shakemap_mineral,
    earthquake_new_madrid_m75_scenario, winter_storm_uri, ...) keep growing as
    more real events are added; giving each its own hue would mean cycling
    colors or repainting existing hazards' color every time a new event is
    registered, both of which break "color encodes hazard identity
    consistently across the whole report." HAZARD_PALETTE is keyed by
    hazard_subtype only for flood's 3 sub-scenarios (surface/river/coastal),
    which are still genuinely one flat "flood" hue in practice -- for
    everything else this falls straight through to hazard_type.
    """
    subtype_key = str(hazard_subtype or "").lower()
    if subtype_key in HAZARD_PALETTE:
        return HAZARD_PALETTE[subtype_key]
    return HAZARD_PALETTE.get(str(hazard_type or "").lower(), _INK_MUTED)


# Real 2022 FAF5 national truck-trip shares by SCTG-G5 commodity group (from
# faf5_sctg_daily_trucks.csv, generated by the upstream DAFNI-NIRD build_faf5_
# sctg_summary.py against faf5_od_matrix_by_sctg.pq). Used only as the
# fallback default in plot_freight_industry_breakdown() -- a national average
# proxy for whichever hazards load_freight_industry_mix() doesn't have a real
# per-hazard mix for yet (see docs/VA_MULTIHAZARD_COMPARISON.md, "Resolved:
# freight-by-industry breakdown"). Real shares come from
# scripts/compute_freight_industry_mix.py, which joins Script 4's disrupted
# freight OD pairs against faf5_od_matrix_by_sctg.pq on the shared
# origin_node/destination_node/Car21 keys.
SCTG_NATIONAL_SHARES: dict[str, float] = {
    "sctg2033": 0.26788208322692302,
    "sctg0109": 0.23384302707182396,
    "sctg1014": 0.20984785923193698,
    "sctg1519": 0.16028548525085405,
    "sctg3499": 0.12814154521846202,
}


def load_freight_industry_mix(
    results_root: Path,
    variant: str,
    summary: pd.DataFrame,
) -> dict[str, dict[str, float]]:
    """Load each hazard's real commodity mix (scripts/compute_freight_industry_mix.py output).

    Reads ``rerouting_analysis/<variant>/<depth_key>/<flood_key>/
    freight_industry_mix.json`` for each row of ``summary`` -- the same
    directory Script 4 already writes its cost CSVs into (``reroute_dir`` in
    ``summarize_single_scenario`` above). Hazards without that file (not yet
    run through ``compute_freight_industry_mix.py``, or zero disrupted
    freight OD pairs so there's nothing to share out) are simply absent from
    the returned dict; ``plot_freight_industry_breakdown``'s per-hazard
    ``.get(row["hazard_label"], SCTG_NATIONAL_SHARES)`` lookup falls back to
    the national proxy for exactly those hazards, so a partially-complete
    real-data run still renders (with the proxy caveat implicitly still
    true only for the missing ones -- pass shares_are_national_proxy=False
    once every hazard in ``summary`` has a real entry here).
    """
    shares_by_hazard: dict[str, dict[str, float]] = {}
    if summary.empty:
        return shares_by_hazard
    for _, row in summary.iterrows():
        if "depth_key" not in row or "flood_key" not in row:
            continue
        mix_path = (
            results_root
            / "rerouting_analysis"
            / variant
            / str(int(row["depth_key"]))
            / str(int(row["flood_key"]))
            / "freight_industry_mix.json"
        )
        if not mix_path.exists():
            continue
        payload = json.loads(mix_path.read_text())
        shares = payload.get("shares") or {}
        if shares:
            shares_by_hazard[str(row["hazard_label"])] = shares
    return shares_by_hazard


def load_direct_damage_by_asset_type(
    results_root: Path,
    variant: str,
    summary: pd.DataFrame,
) -> dict[str, dict[str, float]]:
    """Load each hazard's direct damage split by asset type (bridge/road).

    Reads ``damage_analysis/<variant>/<depth_key>/direct_damage_by_asset_type_
    <flood_key>.json`` -- scripts/compute_direct_damage_by_asset_type.py's
    output. Hazards without that file (script not yet run for that event)
    are simply absent from the returned dict.
    """
    by_hazard: dict[str, dict[str, float]] = {}
    if summary.empty:
        return by_hazard
    for _, row in summary.iterrows():
        if "depth_key" not in row or "flood_key" not in row:
            continue
        path = (
            results_root
            / "damage_analysis"
            / variant
            / str(int(row["depth_key"]))
            / f"direct_damage_by_asset_type_{int(row['flood_key'])}.json"
        )
        if not path.exists():
            continue
        payload = json.loads(path.read_text())
        split = payload.get("by_asset_type_musd") or {}
        if split:
            by_hazard[str(row["hazard_label"])] = split
    return by_hazard


# Direct/baseline comparison pair, adapted from Bor et al.'s io_sector_loss_dodged.py
# (github.com/denniesbor/mhtran) -- a ColorBrewer RdBu-blue pair used there for
# direct-vs-indirect Leontief I-O loss. We don't have an I-O cascade model, but
# the same two-tone dodge cleanly encodes our own real-vs-baseline comparison.
_SHARE_REAL_COLOR = "#2166AC"
_SHARE_BASELINE_COLOR = "#92C5DE"

SCTG_SHORT_LABELS: dict[str, str] = {
    "sctg0109": "Ag/fish/forestry",
    "sctg1014": "Mining",
    "sctg1519": "Petroleum & coal",
    "sctg2033": "Manuf. goods",
    "sctg3499": "Mixed & other",
}


def plot_freight_industry_breakdown(
    summary: pd.DataFrame,
    *,
    industry_shares: dict[str, dict[str, float]] | None = None,
    baseline_shares: dict[str, float] | None = None,
):
    """Per-hazard panels of real vs. national-baseline freight commodity share.

    Design follows Bor et al. 2026 (arXiv:2605.23053, github.com/denniesbor/
    mhtran)'s io_sector_loss_dodged.py: one panel per hazard, categories on the
    y-axis, horizontal dodged bar pairs. That figure dodges direct vs. indirect
    Leontief I-O loss (two independently-computed numbers); we don't have an
    I-O cascade model, so we dodge the equivalent honest pair we DO have --
    each hazard's real disrupted-corridor commodity share (from
    scripts/compute_freight_industry_mix.py) against the flat national average
    share (SCTG_NATIONAL_SHARES) -- so the deviation from baseline is a
    directly-plotted quantity, not something a reader has to infer from subtly
    different bar-chart shapes.

    A hazard with no real share yet (compute_freight_industry_mix.py hasn't
    run for it, or found zero disrupted freight OD pairs) shows only the
    baseline bar, with a small "(real share pending)" note on that panel --
    partial completion is visible per-hazard, not hidden by a global caveat.

    ``industry_shares``: output of ``load_freight_industry_mix(results_root,
    variant, summary)`` -- ``{hazard_label: {sctg_code: share}}``. Omit to
    render baseline-only for every hazard.
    ``baseline_shares``: defaults to SCTG_NATIONAL_SHARES.
    """
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.patches import Patch

    if summary.empty:
        raise ValueError("multihazard summary is empty")

    df = summary.reset_index(drop=True)
    real_shares_by_hazard = industry_shares or {}
    baseline = baseline_shares or SCTG_NATIONAL_SHARES
    sctg_codes = list(SCTG_G5_LABELS.keys())
    y = np.arange(len(sctg_codes))
    bar_h = 0.35
    gap = 0.06

    n = len(df)
    ncols = min(3, n)
    nrows = -(-n // ncols)  # ceil
    plt.rcParams["font.family"] = _FONT_FAMILY
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(4.6 * ncols, 1.3 + 1.35 * len(sctg_codes) * nrows),
        sharex=True, sharey=True, facecolor=_SURFACE, squeeze=False,
    )
    flat_axes = axes.flatten()

    for ax, (_, row) in zip(flat_axes, df.iterrows()):
        hazard_label = str(row["hazard_label"])
        title_color = _hazard_color(row.get("hazard_type", ""), row.get("hazard_subtype", ""))
        real_shares = real_shares_by_hazard.get(hazard_label)
        baseline_vals = np.array([baseline.get(c, 0.0) * 100.0 for c in sctg_codes])

        if real_shares:
            real_vals = np.array([real_shares.get(c, 0.0) * 100.0 for c in sctg_codes])
            ax.barh(
                y - (bar_h / 2 + gap / 2), real_vals, bar_h,
                color=_SHARE_REAL_COLOR, edgecolor=_INK_PRIMARY, linewidth=0.5,
                alpha=0.92, zorder=2,
            )
            ax.barh(
                y + (bar_h / 2 + gap / 2), baseline_vals, bar_h,
                color=_SHARE_BASELINE_COLOR, edgecolor=_INK_PRIMARY, linewidth=0.5,
                alpha=0.92, zorder=2,
            )
        else:
            ax.barh(
                y, baseline_vals, bar_h * 2 + gap,
                color=_SHARE_BASELINE_COLOR, edgecolor=_INK_PRIMARY, linewidth=0.5,
                alpha=0.92, zorder=2,
            )
            ax.text(
                0.98, 0.04, "real share pending", transform=ax.transAxes,
                fontsize=_FS_DATA_LABEL, color=_INK_MUTED, ha="right", va="bottom", style="italic",
            )

        ax.set_yticks(y)
        ax.set_yticklabels([SCTG_SHORT_LABELS[c] for c in sctg_codes], fontsize=_FS_TICK)
        ax.tick_params(axis="x", labelsize=_FS_TICK)
        ax.invert_yaxis()
        ax.set_title(hazard_label, fontsize=_FS_SUBTITLE, color=title_color, loc="left", fontweight="bold")
        _style_axis(ax, horizontal=True, show_gridlines=True)

    for ax in flat_axes[n:]:
        ax.set_visible(False)
    for ax in flat_axes[max(0, n - ncols):n]:
        ax.set_xlabel("Share of disrupted freight (%)", fontsize=_FS_AXIS_LABEL)

    legend_handles = [
        Patch(facecolor=_SHARE_REAL_COLOR, edgecolor=_INK_PRIMARY, linewidth=0.5,
              label="Real disrupted-corridor share"),
        Patch(facecolor=_SHARE_BASELINE_COLOR, edgecolor=_INK_PRIMARY, linewidth=0.5,
              label="National baseline share"),
    ]
    fig.legend(handles=legend_handles, loc="upper right", fontsize=_FS_LEGEND, frameon=False,
               bbox_to_anchor=(0.99, 1.02))
    fig.suptitle(
        "Freight Commodity Mix by Hazard", fontsize=_FS_TITLE, color=_INK_PRIMARY,
        x=0.01, ha="left", y=1.05, fontweight="bold",
    )
    fig.text(
        0.01, 1.012,
        "Real share = each hazard's own disrupted freight corridors. "
        "Baseline = national average commodity mix, unweighted by any hazard.",
        fontsize=_FS_SUBTITLE, color=_INK_SECONDARY, ha="left", va="bottom",
        transform=fig.transFigure,
    )
    fig.text(
        0.01, -0.01,
        "Source: scripts/compute_freight_industry_mix.py (real share, joined against "
        "faf5_od_matrix_by_sctg.pq) and 2022 FAF5 national truck-trip shares (baseline).",
        fontsize=_FS_SOURCE, color=_INK_MUTED, ha="left",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    return fig, axes


def _style_axis(ax, *, horizontal: bool = False, show_gridlines: bool = True) -> None:
    """Urban Institute style-guide axis conventions.

    ``horizontal=True`` for barh charts: gridlines (if any) run on the value
    axis (x), not the category axis (y). Per the style guide, "when directly
    labeling the bars, consider eliminating the...gridlines" -- every chart
    in this module direct-labels its bars, so ``show_gridlines=False`` is the
    right default for new charts; kept True where a caller still wants a
    faint reference grid.
    """
    ax.set_facecolor(_SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(_INK_MUTED)
        ax.spines[side].set_linewidth(0.8)
    if show_gridlines:
        ax.grid(axis="x" if horizontal else "y", color=_GRIDLINE, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    ax.tick_params(colors=_INK_SECONDARY, labelsize=9)
    ax.xaxis.label.set_color(_INK_SECONDARY)
    ax.yaxis.label.set_color(_INK_SECONDARY)


_COST_CATEGORY_COLORS: dict[str, str] = {
    "direct": "#1696D2",      # Urban cyan
    "rerouting": "#EC008B",   # Urban magenta
    "isolation": "#55B748",   # Urban green
}


def plot_multihazard_cost_panels(
    summary: pd.DataFrame,
    *,
    variant: str | None = None,
    exclude_hazards: dict[str, str] | None = None,
    source_note: str = "Source: ResiFlow conus_nandu_v1 pipeline output.",
):
    """Ranked, stacked horizontal comparison of direct, rerouting, and
    isolation cost by hazard -- following Li, Pant et al. (2026), "Stress-
    testing road network resilience using counterfactual flood events",
    Transportation Research Part D 155, Fig. 4 (the same paper Script 4's
    rerouting-cost formula already cites): one bar per hazard, ranked by
    total cost descending, three stacked segments (direct / rerouting /
    isolation) rather than paired bars -- this is the natural comparison
    shape once isolation cost is included, since the three terms sum to a
    single combined cost per hazard, not two independent quantities.

    Unlike Fig. 4, this has NO uncertainty bands -- each hazard here is one
    deterministic day-0 run, not a Morris-sensitivity ensemble. Say so in
    the subtitle rather than implying a false precision Fig. 4 doesn't
    actually have here; add real bands only once a Morris/multi-run ensemble
    exists for these hazards (see docs/PROJECT_LOG.md's Morris/SA items).

    Still follows the Urban Institute Data Visualization Style Guide
    (urbaninstitute.github.io/graphics-styleguide): horizontal bars, category
    labels read horizontally (never rotated), value axis starts at zero --
    no log scale. A known-good number that needs a log axis to stay visible
    next to a known-bad outlier is a sign the outlier shouldn't be in the
    comparison at all (see ``exclude_hazards``), not a reason for a log axis.

    ``exclude_hazards``: ``{hazard_label: reason}`` -- omit these hazards'
    bars entirely rather than plot a number known to be wrong; each reason
    is listed in the source note instead. Use for a hazard whose cost source
    is a known-bad placeholder, e.g. winter storm's flood-shim direct cost.
    """
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.patches import Patch

    if summary.empty:
        raise ValueError("multihazard summary is empty")

    resolved_variant = variant or (
        str(summary["variant"].iloc[0]) if "variant" in summary.columns else ""
    )
    exclude_hazards = exclude_hazards or {}
    df = summary[~summary["hazard_label"].isin(exclude_hazards)].copy()
    if df.empty:
        raise ValueError("All hazards were excluded -- nothing left to plot")

    df["_direct"] = pd.to_numeric(df["direct_damage_usd"], errors="coerce").fillna(0.0)
    df["_rerouting"] = (
        pd.to_numeric(df["rerouting_cost_freight_usd"], errors="coerce").fillna(0.0)
        + pd.to_numeric(df.get("rerouting_cost_passenger_usd", 0.0), errors="coerce").fillna(0.0)
    )
    df["_isolation"] = pd.to_numeric(df.get("isolation_cost_usd", 0.0), errors="coerce").fillna(0.0)
    df["_total"] = df["_direct"] + df["_rerouting"] + df["_isolation"]

    # Ranked by total cost descending, largest at top (matches Fig. 4).
    df = df.sort_values("_total", ascending=True).reset_index(drop=True)

    labels = df["hazard_label"].astype(str).tolist()
    unit = resolve_cost_display_unit(float(df["_total"].max()), variant=resolved_variant)
    divisor = {"usd": 1.0, "kusd": 1e3, "musd": 1e6, "busd": 1e9}[unit]
    unit_label = {
        "usd": "USD", "kusd": "USD (thousands)", "musd": "USD (millions)", "busd": "USD (billions)",
    }[unit]

    plt.rcParams["font.family"] = _FONT_FAMILY
    fig, ax = plt.subplots(figsize=(11.5, 0.62 * len(labels) + 2.6), facecolor=_SURFACE)
    y = np.arange(len(labels))
    bar_h = 0.58

    left = np.zeros(len(labels))
    for key, category_label in (("_direct", "Direct"), ("_rerouting", "Rerouting"), ("_isolation", "Isolation")):
        vals = (df[key] / divisor).to_numpy()
        ax.barh(
            y, vals, bar_h, left=left,
            color=_COST_CATEGORY_COLORS[key.strip("_")], edgecolor=_SURFACE, linewidth=0.6,
            zorder=2, label=category_label,
        )
        left = left + vals

    for yi, total_usd in zip(y, df["_total"]):
        ax.annotate(
            format_cost(float(total_usd), variant=resolved_variant),
            (total_usd / divisor, yi),
            xytext=(6, 0), textcoords="offset points", ha="left", va="center",
            fontsize=_FS_DATA_LABEL, color=_INK_PRIMARY, fontweight="bold",
        )

    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=_FS_TICK)
    ax.set_ylim(-0.6, len(labels) - 1 + 0.6)
    ax.set_xlim(0, float(left.max() or 1.0) * 1.18)
    ax.set_xlabel(unit_label, fontsize=_FS_AXIS_LABEL)
    ax.tick_params(axis="x", labelsize=_FS_TICK)
    _style_axis(ax, horizontal=True, show_gridlines=False)

    legend_handles = [
        Patch(facecolor=color, edgecolor=_SURFACE, linewidth=0.6, label=label)
        for label, color in (
            ("Direct", _COST_CATEGORY_COLORS["direct"]),
            ("Rerouting", _COST_CATEGORY_COLORS["rerouting"]),
            ("Isolation", _COST_CATEGORY_COLORS["isolation"]),
        )
    ]
    ax.legend(
        handles=legend_handles, loc="lower right", bbox_to_anchor=(1.0, 1.02),
        ncol=3, fontsize=_FS_LEGEND, frameon=False,
    )

    fig.suptitle(
        "Multi-Hazard Direct, Rerouting, and Isolation Cost", fontsize=_FS_TITLE,
        color=_INK_PRIMARY, x=0.02, ha="left", y=1.1, fontweight="bold",
    )
    fig.text(
        0.02, 1.03,
        "Ranked by total cost. No uncertainty bands -- each bar is one deterministic run, not an ensemble.",
        fontsize=_FS_SUBTITLE, color=_INK_SECONDARY, ha="left", va="bottom", transform=fig.transFigure,
    )

    notes = [source_note]
    for label, reason in exclude_hazards.items():
        notes.append(f"{label} excluded: {reason}")
    fig.text(0.02, -0.04, "\n".join(notes), fontsize=_FS_SOURCE, color=_INK_MUTED, ha="left", va="top")
    fig.tight_layout()
    return fig, ax


def plot_ranked_cost_by_asset_type(
    summary: pd.DataFrame,
    *,
    variant: str | None = None,
    asset_type_split: dict[str, dict[str, float]] | None = None,
    exclude_hazards: dict[str, str] | None = None,
    source_note: str = "Source: ResiFlow conus_nandu_v1 pipeline output.",
):
    """Direct damage decomposed by asset type (bridge vs. road), ranked by total.

    Single horizontal panel -- an earlier two-panel version also ranked total
    cost, redundant with plot_multihazard_cost_panels' own direct-vs-indirect
    bars and dropped for that reason. Zero-based linear axis, no log scale
    (see plot_multihazard_cost_panels' docstring for why), each segment
    directly labeled via format_cost.

    ``asset_type_split``: output of ``load_direct_damage_by_asset_type(
    results_root, variant, summary)``. A hazard missing from it renders a
    single unsplit direct-damage bar with a "split pending" note, same
    partial-completion pattern as plot_freight_industry_breakdown.
    ``exclude_hazards``: same convention as plot_multihazard_cost_panels.
    """
    import matplotlib.pyplot as plt
    import numpy as np
    from matplotlib.patches import Patch

    if summary.empty:
        raise ValueError("multihazard summary is empty")

    resolved_variant = variant or (
        str(summary["variant"].iloc[0]) if "variant" in summary.columns else ""
    )
    exclude_hazards = exclude_hazards or {}
    df = summary[~summary["hazard_label"].isin(exclude_hazards)].reset_index(drop=True).copy()
    if df.empty:
        raise ValueError("All hazards were excluded -- nothing left to plot")
    df["direct_damage_usd"] = pd.to_numeric(df.get("direct_damage_usd", 0.0), errors="coerce").fillna(0.0)
    df = df.sort_values("direct_damage_usd", ascending=True).reset_index(drop=True)  # ascending: barh draws bottom-up
    splits = asset_type_split or {}

    labels = df["hazard_label"].astype(str).tolist()
    colors = [
        _hazard_color(row.get("hazard_type", ""), row.get("hazard_subtype", ""))
        for _, row in df.iterrows()
    ]
    direct = df["direct_damage_usd"]
    bridge_vals = np.array([splits.get(lbl, {}).get("bridge", float("nan")) * 1e6 for lbl in labels])
    road_vals = np.array([splits.get(lbl, {}).get("road", float("nan")) * 1e6 for lbl in labels])
    has_split = ~np.isnan(bridge_vals)

    max_abs = float(pd.concat([direct, pd.Series(bridge_vals), pd.Series(road_vals)]).abs().max() or 0.0)
    unit = resolve_cost_display_unit(max_abs, variant=resolved_variant)
    divisor = {"usd": 1.0, "kusd": 1e3, "musd": 1e6, "busd": 1e9}[unit]
    unit_label = {"usd": "USD", "kusd": "USD (thousands)", "musd": "USD (millions)", "busd": "USD (billions)"}[unit]

    plt.rcParams["font.family"] = _FONT_FAMILY
    fig, ax = plt.subplots(1, 1, figsize=(10, 0.75 * len(labels) + 2.7), facecolor=_SURFACE)
    y = np.arange(len(labels))
    bar_h = 0.34

    for yi, (lbl, color, has, bv, rv, dtotal) in enumerate(
        zip(labels, colors, has_split, bridge_vals, road_vals, direct)
    ):
        if has:
            ax.barh(yi - bar_h / 2, bv / divisor, bar_h, color=color,
                     edgecolor=_INK_PRIMARY, linewidth=0.6, zorder=2)
            ax.barh(yi + bar_h / 2, rv / divisor, bar_h, color=color,
                     edgecolor=_INK_PRIMARY, linewidth=0.6, hatch="////", alpha=0.55, zorder=2)
            ax.annotate(format_cost(bv, variant=resolved_variant), (max(bv / divisor, 0.0), yi - bar_h / 2),
                        xytext=(5, 0), textcoords="offset points", ha="left", va="center",
                        fontsize=_FS_DATA_LABEL, color=_INK_SECONDARY)
            ax.annotate(format_cost(rv, variant=resolved_variant), (max(rv / divisor, 0.0), yi + bar_h / 2),
                        xytext=(5, 0), textcoords="offset points", ha="left", va="center",
                        fontsize=_FS_DATA_LABEL, color=_INK_SECONDARY)
        else:
            ax.barh(yi, dtotal / divisor, bar_h * 2 + 0.06, color=color,
                     edgecolor=_INK_PRIMARY, linewidth=0.6, alpha=0.55, zorder=2)
            ax.annotate(
                f"{format_cost(dtotal, variant=resolved_variant)} (asset-type split pending)",
                (max(dtotal / divisor, 0.0), yi),
                xytext=(5, 0), textcoords="offset points", ha="left", va="center",
                fontsize=_FS_DATA_LABEL, color=_INK_MUTED, style="italic",
            )
    ax.set_yticks(y)
    ax.set_yticklabels(labels, fontsize=_FS_TICK)
    ax.set_xlabel(unit_label, fontsize=_FS_AXIS_LABEL)
    ax.tick_params(axis="x", labelsize=_FS_TICK)
    # No axes-level title here -- a single-panel chart doesn't need one
    # alongside the figure title+subtitle below (unlike the two-panel
    # charts, where each subplot needs its own title to tell them apart).
    max_val = float(pd.concat([direct, pd.Series(bridge_vals), pd.Series(road_vals)]).max() / divisor or 1.0)
    ax.set_xlim(0, max_val * 1.55)
    _style_axis(ax, horizontal=True, show_gridlines=False)

    legend_handles = [
        Patch(facecolor=_INK_MUTED, edgecolor=_INK_PRIMARY, linewidth=0.6, label="Bridge"),
        Patch(facecolor=_INK_MUTED, edgecolor=_INK_PRIMARY, linewidth=0.6, hatch="////", alpha=0.55, label="Road"),
    ]
    ax.legend(handles=legend_handles, loc="lower right", fontsize=_FS_LEGEND, frameon=False)

    fig.suptitle(
        "Multi-Hazard Direct Damage by Asset Type", fontsize=_FS_TITLE, color=_INK_PRIMARY,
        x=0.02, ha="left", y=1.12, fontweight="bold",
    )
    fig.text(
        0.02, 1.04,
        "Which hazards' direct damage falls on bridges versus ordinary roads, ranked by total.",
        fontsize=_FS_SUBTITLE, color=_INK_SECONDARY, ha="left", va="bottom", transform=fig.transFigure,
    )
    notes = [source_note]
    for label, reason in exclude_hazards.items():
        notes.append(f"{label} excluded: {reason}")
    fig.text(0.02, -0.03, "\n".join(notes), fontsize=_FS_SOURCE, color=_INK_MUTED, ha="left", va="top")
    fig.tight_layout()
    return fig, ax


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


_DAMAGE_LEVEL_ORDINAL: dict[str, int] = {"no": 0, "minor": 1, "moderate": 2, "extensive": 3, "severe": 4}


def plot_multihazard_damage_maps(
    links_by_hazard: dict[str, gpd.GeoDataFrame],
    *,
    hazard_meta: dict[str, dict[str, str]] | None = None,
    max_edges: int | None = None,
):
    """Small-multiple CONUS maps of per-link damage level, one panel per hazard.

    Follows Bor et al. 2026 (arXiv:2605.23053, github.com/denniesbor/mhtran)'s
    Fig. 3/6 pattern: a grid of small-multiple maps sharing ONE color scale so
    magnitudes are comparable across panels, not just within one. We use
    damage_level_max's ordinal (no/minor/moderate/extensive/severe -> 0-4)
    rather than a dollar value, since that column is reliably present at
    link-geometry level for every hazard already (Script 2's output), unlike
    per-row HAZUS dollar costs which currently only exist in Script 3's
    separate, non-geometry CSV -- this keeps the map real and consistent
    across all hazards rather than mixing a $-based scale for HAZUS-priced
    hazards with something else for the rest.

    Undamaged links render as a faint gray context layer (the network's own
    shape reads as the CONUS outline at this density -- no separate
    basemap/state-boundary dependency needed). Damaged links use a single-hue
    sequential colormap (magnitude, not identity -- see dataviz conventions),
    shared across every panel via one Normalize instance + one colorbar.

    ``links_by_hazard``: ``{hazard_label: gdf}`` with a ``damage_level_max``
    column and geometry -- caller loads/subsets these (e.g. via
    ``subset_links_for_map``) since CONUS-scale I/O and edge-count capping is
    already handled there; this function only renders.
    ``hazard_meta``: optional ``{hazard_label: {"hazard_type":..., "hazard_subtype":...}}``
    for panel-title coloring (falls back to muted ink if omitted).
    ``max_edges``: re-applies ``subset_links_for_map`` per panel as a safety
    net even if the caller already subsetted (cheap no-op when already small).
    """
    import matplotlib.pyplot as plt
    from matplotlib.cm import ScalarMappable
    from matplotlib.colors import LinearSegmentedColormap, Normalize
    from matplotlib.lines import Line2D

    if not links_by_hazard:
        raise ValueError("links_by_hazard is empty")

    hazard_meta = hazard_meta or {}
    cmap = LinearSegmentedColormap.from_list(
        "damage_severity", ["#fee8c8", "#fdbb84", "#fc8d59", "#e34a33", "#b30000"]
    )
    norm = Normalize(vmin=0, vmax=4)

    labels = list(links_by_hazard.keys())
    n = len(labels)
    ncols = min(3, n)
    nrows = -(-n // ncols)
    plt.rcParams["font.family"] = "sans-serif"
    fig, axes = plt.subplots(
        nrows, ncols, figsize=(4.6 * ncols, 3.0 * nrows), facecolor=_SURFACE, squeeze=False,
    )
    flat_axes = axes.flatten()

    for ax, label in zip(flat_axes, labels):
        gdf = links_by_hazard[label]
        if max_edges:
            gdf = subset_links_for_map(gdf, max_edges=max_edges, min_flow=-1.0)
        levels = gdf.get("damage_level_max", pd.Series(dtype=object)).astype(str).str.lower()
        ordinal = levels.map(_DAMAGE_LEVEL_ORDINAL).fillna(0).astype(int)
        undamaged = gdf.loc[ordinal == 0]
        damaged = gdf.loc[ordinal > 0]

        if not undamaged.empty:
            undamaged.plot(ax=ax, color=_GRIDLINE, linewidth=0.35, zorder=1)
        if not damaged.empty:
            damaged.plot(
                ax=ax, color=cmap(norm(ordinal.loc[damaged.index])),
                linewidth=1.1, zorder=2,
            )

        meta = hazard_meta.get(label, {})
        title_color = _hazard_color(meta.get("hazard_type", ""), meta.get("hazard_subtype", ""))
        ax.set_title(
            f"{label}  (n={len(damaged):,} damaged / {len(gdf):,})",
            fontsize=10.5, color=title_color, fontweight="bold", loc="left",
        )
        ax.set_facecolor(_SURFACE)
        ax.set_xticks([])
        ax.set_yticks([])
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.set_aspect("equal")

    for ax in flat_axes[n:]:
        ax.set_visible(False)

    sm = ScalarMappable(norm=norm, cmap=cmap)
    sm.set_array([])
    cbar = fig.colorbar(
        sm, ax=flat_axes[:n], orientation="horizontal", fraction=0.03, pad=0.04, aspect=40,
    )
    cbar.set_ticks([1, 2, 3, 4])
    cbar.set_ticklabels(["minor", "moderate", "extensive", "severe"])
    cbar.ax.tick_params(labelsize=9, colors=_INK_SECONDARY)
    cbar.outline.set_visible(False)
    context_handle = Line2D([0], [0], color=_GRIDLINE, linewidth=1.5, label="Undamaged link")
    fig.legend(handles=[context_handle], loc="lower left", fontsize=8.5, frameon=False,
               bbox_to_anchor=(0.01, 0.0))

    fig.suptitle("Damaged network extent by hazard", fontsize=14, color=_INK_PRIMARY, y=0.99)
    return fig, axes
