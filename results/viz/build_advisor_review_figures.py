"""Build RQ-organized advisor-review figures from visual_registry.csv.

The registry is the authoritative spec. This script filters the tomorrow
headline figure set, uses each row's dimensions, and falls back to synthetic
layout data when a referenced data table is absent.
"""

from __future__ import annotations

import csv
import json
import sys
from io import BytesIO
import html
import math
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path

import matplotlib as mpl
import matplotlib.patheffects as pe
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.patches import Patch, Rectangle

from figlib import synthetic_model


ROOT = Path(__file__).resolve().parents[2]
VIZ_DIR = ROOT / "results" / "viz"
REGISTRY_PATH = VIZ_DIR / "visual_registry.csv"
SHOW_DATA_LABELS = "--no-data-labels" not in sys.argv
OUT_DIR = VIZ_DIR / "advisor_review"
if not SHOW_DATA_LABELS:
    OUT_DIR = OUT_DIR / "no_data_labels"

HAZARDS = ["Hurricane Harvey", "New Madrid Earthquake", "New Madrid Landslide", "Winter Storm Jonas"]
HAZARD_LABELS = {
    "Hurricane Harvey": "Hurricane\nHarvey",
    "New Madrid Earthquake": "New Madrid\nEarthquake",
    "New Madrid Landslide": "New Madrid\nLandslide",
    "Winter Storm Jonas": "Winter Storm\nJonas",
}
COMPOSITION_MAGNITUDE = False  # RQ3 A: bar length = total cost, segments = industry mix (labeled_v3)
NUMBER_GROUPS = True  # (i)-(iv) prefix on grouped event labels; the labeled_v2 build turns it off
HAZARD_COLORS = {
    "Hurricane Harvey": "#56B4E9",
    "New Madrid Earthquake": "#D55E00",
    "New Madrid Landslide": "#8C510A",
    "Winter Storm Jonas": "#009E73",
}
COST_COLORS = {
    "Direct": "#3d4d5c",
    "Rerouting": "#3a7ca5",
    "Isolation": "#e1a730",
}
SEVERITY_COLORS = {
    "Minor": "#c7dcef",
    "Moderate": "#6baed6",
    "Severe": "#2171b5",
}
INDUSTRY_COLORS = {
    "Agriculture, fishing, forestry": "#4c9f85",
    "Mining": "#e8c65e",
    "Petroleum & coal products": "#c26a3d",
    "Manufactured goods": "#4E79A7",
    "Mixed freight & other": "#c9cdd2",
}

STATE_POOL = {
    "Hurricane Harvey": ["Texas", "Louisiana", "Mississippi", "Arkansas", "Oklahoma"],
    "New Madrid Earthquake": ["Missouri", "Arkansas", "Tennessee", "Illinois", "Kentucky"],
    "New Madrid Landslide": ["West Virginia", "Kentucky", "Virginia", "Tennessee", "North Carolina"],
    "Winter Storm Jonas": ["New York", "Pennsylvania", "Virginia", "Maryland", "New Jersey"],
}
FACILITY_TYPES = ["Interstate", "Arterial", "Collector", "Local road", "Bridges"]
OUTPUT_NAMES = {
    "s3_major_cost_panel_a_facility": "RQ1a_direct_cost_by_road_category",
    "s3_major_cost_panel_b_state": "RQ1b_direct_cost_by_top_states",
    "x_ranked_states_4metric": "RQ1c_costs_across_affected_states",
    "s4_rerouting_components": "RQ2a_rerouting_cost_components",
    "s4_freight_passenger_rerouting_isolation": "RQ2b_rerouting_and_isolation_by_flow",
    "x_sankey_cost_flow_state": "RQ2c_total_cost_by_state_and_flow",
    "x_freight_commodity_delta": "RQ3a_industry_share_of_disrupted_freight_cost",
    "x_top5_states_industry": "RQ3b_freight_cost_disrupted_by_industry_in_top_states",
}

PNG_DPI = 300
SENTENCE_CASE_XLABELS = True


@dataclass
class BuildRecord:
    row_id: str
    rq_group: str
    rq_tag: str
    chart_type: str
    data_status: str
    pdf: str
    png: str
    resolved_caveats: str
    open_caveats: str
    axis_x: float = 0.0


def apply_style() -> None:
    mpl.rcParams.update(
        {
            "font.family": "Times New Roman",
            "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
            "font.size": 12,
            "axes.titlesize": 12,
            "axes.labelsize": 12,
            "xtick.labelsize": 12,
            "ytick.labelsize": 12,
            "legend.fontsize": 12,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "axes.axisbelow": True,
            "grid.color": "#e6e6e6",
            "grid.linewidth": 0.5,
            "axes.linewidth": 0.6,
            "legend.frameon": False,
            "pdf.fonttype": 42,
            "ps.fonttype": 42,
            "savefig.dpi": 1000,
            "figure.dpi": 150,
        }
    )


def load_registry() -> pd.DataFrame:
    return pd.read_csv(REGISTRY_PATH, keep_default_na=False)


def rq_group(rq_tag: str) -> str | None:
    match = re.match(r"^(RQ[123])", str(rq_tag).strip())
    return match.group(1) if match else None


def filtered_rows(registry: pd.DataFrame) -> pd.DataFrame:
    rq = registry["rq_tag"].astype(str).str.strip()
    main = registry["inclusion_status"].eq("Main")
    candidate_rq = registry["inclusion_status"].eq("Candidate") & rq.str.startswith(("RQ1", "RQ2", "RQ3"))
    keep = (main | candidate_rq) & ~registry["category"].eq("Diagnostic")
    keep &= rq.ne("") & rq.ne("Supplementary")
    out = registry.loc[keep].copy()
    out["rq_group"] = out["rq_tag"].map(rq_group)
    out = out[out["rq_group"].notna()]
    out = out[~out["chart_type"].eq("table")]
    return out.reset_index(drop=True)


def candidate_table_names(data_source: str) -> list[str]:
    names = []
    for token in re.split(r"[,/+]", str(data_source)):
        token = token.strip()
        match = re.search(r"([\w.-]+\.(?:csv|parquet|pq|gpq|duckdb))", token)
        if match:
            names.append(match.group(1))
    return names


def find_existing_table(row: pd.Series) -> Path | None:
    for name in candidate_table_names(row.get("data_source", "")):
        direct = ROOT / name
        if direct.exists():
            return direct
        matches = list(ROOT.rglob(name))
        if matches:
            return matches[0]
    return None


def read_existing_table(path: Path) -> pd.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return pd.read_csv(path)
    if suffix in {".pq", ".gpq", ".parquet"}:
        return pd.read_parquet(path)
    if suffix == ".duckdb":
        import duckdb

        with duckdb.connect(str(path), read_only=True) as con:
            tables = con.execute("SHOW TABLES").fetchdf()
            if tables.empty:
                return pd.DataFrame()
            return con.execute(f"SELECT * FROM {tables.iloc[0, 0]} LIMIT 5000").fetchdf()
    return pd.DataFrame()


def stable_rng(row_id: str) -> np.random.Generator:
    seed = sum((idx + 1) * ord(ch) for idx, ch in enumerate(row_id)) % (2**32)
    return np.random.default_rng(seed)


def synthetic_data(row: pd.Series) -> pd.DataFrame:
    row_id = row["id"]
    consistent = synthetic_model.table(row_id)  # one reconciled synthetic world (figlib/synthetic_model.py)
    if consistent is not None:
        return consistent
    rng = stable_rng(row_id)
    rows: list[dict[str, object]] = []

    if row_id == "s3_major_cost_panel_a_facility":
        for hazard in HAZARDS:
            total = rng.uniform(0.4, 9.0)
            weights = rng.dirichlet(np.ones(len(FACILITY_TYPES)) * 1.7)
            for facility, share in zip(FACILITY_TYPES, weights):
                severity = rng.dirichlet(np.ones(len(SEVERITY_COLORS)) * 1.4)
                item = {"hazard": hazard, "facility_type": facility}
                for level, severity_share in zip(SEVERITY_COLORS, severity):
                    item[level] = total * share * severity_share
                rows.append(item)
        return pd.DataFrame(rows)

    if row_id in {"s3_major_cost_panel_b_state", "x_cost_by_state_flow_long", "x_state_rank_labels"}:
        for hazard in HAZARDS:
            for rank, state in enumerate(STATE_POOL[hazard], start=1):
                base = rng.uniform(0.15, 4.0) / rank
                rows.append(
                    {
                        "hazard": hazard,
                        "geo_id": state,
                        "geo_level": "state",
                        "geo_scope": "affected" if rank <= 3 else "neighboring",
                        "rank": rank,
                        "Direct": base,
                        "Direct_error": base * rng.uniform(0.08, 0.18),
                        "Rerouting": base * rng.uniform(0.2, 0.7),
                        "Isolation": base * rng.uniform(0.05, 0.35),
                    }
                )
        return pd.DataFrame(rows)

    if row_id == "s4_rerouting_components":
        for hazard in HAZARDS:
            for component in ["Time", "Operate", "Toll"]:
                rows.append({"hazard": hazard, "component": component, "cost": rng.uniform(20, 900)})
        return pd.DataFrame(rows)

    if row_id == "s4_freight_passenger_rerouting_isolation":
        for hazard in HAZARDS:
            for flow in ["Freight", "Passenger"]:
                for component in ["Rerouting", "Isolation"]:
                    rows.append(
                        {
                            "hazard": hazard,
                            "flow": flow,
                            "component": component,
                            "cost": rng.uniform(20, 1000) * (0.45 if flow == "Freight" else 1.0),
                        }
                    )
        return pd.DataFrame(rows)

    if row_id == "x_state_topN_coverage_table":
        for hazard in HAZARDS:
            for n in [1, 2, 3, 5, 10]:
                rows.append({"hazard": hazard, "N": n, "coverage_pct": min(98, 25 + 16 * math.log2(n + 1) + rng.uniform(-4, 4))})
        return pd.DataFrame(rows)

    if row_id == "x_sankey_cost_flow_state":
        for hazard in HAZARDS:
            for state in STATE_POOL[hazard][:4] + ["Rest"]:
                rows.append(
                    {
                        "hazard": hazard,
                        "state": state,
                        "Direct": rng.uniform(0.2, 3.8),
                        "Rerouting": rng.uniform(0.1, 2.1),
                        "Isolation": rng.uniform(0.05, 0.9),
                    }
                )
        return pd.DataFrame(rows)

    if row_id == "x_ranked_states_4metric":
        metrics = ["Total", "Per lane-mile", "Per freight value", "Per capita"]
        for hazard in HAZARDS:
            for metric in metrics:
                for state in STATE_POOL[hazard][:3]:
                    total = rng.uniform(0.2, 9.0)
                    shares = rng.dirichlet(np.array([2.2, 1.2, 0.8]))
                    rows.append(
                        {
                            "hazard": hazard,
                            "metric": metric,
                            "state": state,
                            "Direct": total * shares[0],
                            "Rerouting": total * shares[1],
                            "Isolation": total * shares[2],
                            "value": total,
                        }
                    )
        return pd.DataFrame(rows)

    if row_id == "x_freight_commodity_delta":
        for hazard in HAZARDS:
            for commodity in INDUSTRY_COLORS:
                rows.append(
                    {
                        "hazard": hazard,
                        "commodity": commodity,
                        "delta": rng.uniform(-10, 10),
                        "comparison": "disrupted freight share minus affected-state output share",
                    }
                )
        return pd.DataFrame(rows)

    if row_id == "x_top5_states_industry":
        for hazard in HAZARDS:
            for state in STATE_POOL[hazard]:
                weights = rng.dirichlet(np.ones(len(INDUSTRY_COLORS)) * 1.3)
                total = rng.uniform(0.4, 8.0)
                for industry, share in zip(INDUSTRY_COLORS, weights):
                    rows.append({"hazard": hazard, "state": state, "industry": industry, "cost": total * share})
        return pd.DataFrame(rows)

    if row_id == "x_geo_scope_labels":
        for hazard in HAZARDS:
            for state in STATE_POOL[hazard]:
                rows.append({"hazard": hazard, "geo_id": state, "geo_level": "state", "geo_scope": "affected"})
        return pd.DataFrame(rows)

    return pd.DataFrame({"hazard": HAZARDS, "value": rng.uniform(1, 10, len(HAZARDS))})


def load_or_synthetic(row: pd.Series) -> tuple[pd.DataFrame, str]:
    if row["id"] in {"x_ranked_states_4metric", "x_freight_commodity_delta"}:
        source_id = "s3_major_cost_panel_b_state" if row["id"] == "x_ranked_states_4metric" else "x_top5_states_industry"
        source = load_registry().set_index("id").loc[source_id].copy()
        source["id"] = source_id
        return load_or_synthetic(source)
    path = find_existing_table(row)
    if path is None:
        return synthetic_data(row), "synthetic"
    data = read_existing_table(path)
    if data.empty:
        return synthetic_data(row), "synthetic"
    return data, f"real: {path.relative_to(ROOT)}"


def wrap_label(label: str, width: int = 18) -> str:
    return "\n".join(textwrap.wrap(str(label), width=width, break_long_words=False)) or str(label)


def finish_labels_and_legends(fig: plt.Figure, *, scale: float = 1.65, value_fontsize: float = 12, relayout: bool = True) -> None:
    """Place component values and use a measured 10-point gap below axis labels."""
    fig.set_size_inches(fig.get_size_inches() * scale)
    if relayout and fig.get_label() == "rq1c":
        fig.tight_layout(rect=(0, .055, 1, 1), h_pad=.7, w_pad=2)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for ax in fig.axes:
        rotated = [t for t in ax.texts if t.get_rotation() == 90]
        if rotated:
            tick_left = min(t.get_window_extent(renderer).x0 for t in ax.get_yticklabels() if t.get_visible())
            outer_left = tick_left
            for text in rotated:
                width = text.get_window_extent(renderer).width
                center = tick_left - 7 * fig.dpi / 72 - width / 2
                text.set_x(ax.transAxes.inverted().transform((center, 0))[0])
                outer_left = min(outer_left, center - width / 2 - 5 * fig.dpi / 72)
            left = ax.transAxes.inverted().transform((outer_left, 0))[0]
            for patch in ax.patches:
                if patch.get_zorder() == -1:
                    patch.set_x(left)
                    patch.set_width(1 - left)
    for text in fig.texts:
        if text.get_gid() == "shared-x-label":
            tick_bottom = min(t.get_window_extent(renderer).y0 for ax in fig.axes
                              for t in ax.get_xticklabels() if t.get_visible())
            text.set_va("top")
            text.set_y((tick_bottom - 7 * fig.dpi / 72) / fig.bbox.height)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for ax in fig.axes:
        containers = [c for c in ax.containers if isinstance(c, mpl.container.BarContainer)]
        if not SHOW_DATA_LABELS or len(containers) < 2:
            continue
        # Segments rendered too thin to read get no callout: at this density
        # (many stacked segments per row, one row's total sometimes 10x
        # another's), a leader-line label for every sliver was the actual
        # source of the crowding -- dozens of overlapping callouts competing
        # for the same few points of vertical space above a row. Judging
        # "too thin" from the bar's own rendered pixel width (not a share of
        # the whole axis, which one outlier row can dominate) means a small
        # value on a small row still gets labeled while the same absolute
        # value on a row dominated by one huge segment does not -- matching
        # which one is actually legible. The color-coded segment itself is
        # never removed (still visible in the bar and the legend), only its
        # text label is dropped once it's reliably illegible anyway.
        min_segment_px = 6.0
        last_right = {}
        row_totals = {}
        for container in containers:
            for bar in container:
                key = round(bar.get_y() + bar.get_height() / 2, 4)
                row_totals[key] = row_totals.get(key, 0) + bar.get_width()
        for container in containers:
            for bar in container:
                value = bar.get_width()
                y = bar.get_y() + bar.get_height() / 2
                x = bar.get_x() + value / 2
                if ax.get_gid() != "composition" and bar.get_window_extent(renderer).width < min_segment_px:
                    continue
                label = f"{(value / row_totals[round(y, 4)] * 100 if COMPOSITION_MAGNITUDE else value):.1f}%" if ax.get_gid() == "composition" else ("<0.01" if 0 < value < .005 else (f"{value:,.2f}" if value < 20 else f"{value:,.0f}"))
                color = "black"
                halo = [pe.withStroke(linewidth=1.5, foreground="white"), pe.Normal()]
                text = ax.text(x, y, label, ha="center", va="center", fontsize=value_fontsize, color=color)
                width = text.get_window_extent(renderer).width
                bounds = bar.get_window_extent(renderer)
                if bounds.width < width + 5:
                    text.remove()
                    anchor = ax.transData.transform((x, y))
                    center = max(anchor[0], last_right.get(y, -1e9) + width / 2 + 4)
                    last_right[y] = center + width / 2
                    ax.annotate(label, (x, y - bar.get_height()/2),
                                xytext=((center-anchor[0])*72/fig.dpi, 5),
                                textcoords="offset points", ha="center", va="bottom", fontsize=value_fontsize,
                                arrowprops=dict(arrowstyle="-", color="#777777", lw=.45),
                                color=color, path_effects=halo)
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    labels = [ax.xaxis.label for ax in fig.axes if ax.get_xlabel()]
    labels += [t for t in fig.texts if t.get_gid() == "shared-x-label"]
    if not labels:
        return
    bottom = min(t.get_window_extent(renderer).y0 for t in labels)
    legends = list(fig.legends) + [ax.get_legend() for ax in fig.axes if ax.get_legend()]
    for legend in legends:
        legend.set_loc("upper center")
        legend.set_bbox_to_anchor((.5, (bottom - 10*fig.dpi/72)/fig.bbox.height), transform=fig.transFigure)
        legend.borderaxespad = 0


def save_figure(fig: plt.Figure, row: pd.Series) -> tuple[Path, Path, float]:
    finish_labels_and_legends(fig)
    folder = OUT_DIR / row["rq_group"]
    folder.mkdir(parents=True, exist_ok=True)
    stem = OUTPUT_NAMES.get(str(row["id"]), str(row["id"]))
    pdf = folder / f"{stem}.pdf"
    png = folder / f"{stem}.png"
    fig.canvas.draw()
    tight = fig.get_tightbbox(fig.canvas.get_renderer())
    axis_x = (fig.axes[0].get_position().x0 * fig.get_figwidth() - tight.x0
              + mpl.rcParams["savefig.pad_inches"]) * 72
    fig.savefig(pdf, bbox_inches="tight")
    temporary_png = png.with_suffix(".tmp.png")
    fig.savefig(temporary_png, dpi=PNG_DPI, bbox_inches="tight")
    temporary_png.replace(png)
    plt.close(fig)
    return pdf, png, axis_x


def stacked_barh(
    ax: plt.Axes,
    labels: list[str],
    values_by_component: dict[str, np.ndarray],
    colors: dict[str, str],
    *,
    legend: bool = True,
) -> None:
    y = np.arange(len(labels))
    left = np.zeros(len(labels))
    for component, values in values_by_component.items():
        ax.barh(y, values, left=left, color=colors.get(component, "#999999"), label=component, height=0.52)
        left += values
    for yi, total in enumerate(left):
        ax.annotate(f"{total:,.2f}",
                    (total, yi), xytext=(9, 0), textcoords="offset points",
                    va="center", fontsize=12, color="#777777")
    ax.set_xlim(0, max(ax.get_xlim()[1], max(left) * 1.17))
    ax.grid(axis="y", visible=False)
    ax.set_yticks(y, labels)
    ax.invert_yaxis()
    if legend:
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.085), ncol=3)


def grouped_hazard_labels(ax: plt.Axes, hazards: pd.Series, *, x: float = -0.14,
                          box: bool = True, three_line: bool = False, numbered: bool = False) -> None:
    starts: list[tuple[str, int, int]] = []
    current = str(hazards.iloc[0])
    start = 0
    for idx, hazard in enumerate(hazards.astype(str).iloc[1:], start=1):
        if hazard != current:
            starts.append((current, start, idx - 1))
            current = hazard
            start = idx
    starts.append((current, start, len(hazards) - 1))
    for hazard, first, last in starts:
        if box:
            ax.add_patch(Rectangle((x - 0.055, first - 0.48), 1 - x + 0.055,
                                   last - first + 0.96, transform=ax.get_yaxis_transform(),
                                   facecolor="#fafafa", edgecolor="#dddddd", linewidth=0.7,
                                   clip_on=False, zorder=-1))
        label = HAZARD_LABELS.get(hazard, hazard)
        if three_line and hazard in {"New Madrid Earthquake", "New Madrid Landslide"}:
            label = label.replace("New Madrid\n", "New\nMadrid\n")
        if three_line and hazard == "Winter Storm Jonas":
            label = label.replace("Winter Storm\n", "Winter\nStorm\n")
        if numbered:
            label = f"({['i','ii','iii','iv'][[t[0] for t in starts].index(hazard)]}) {label}"
        ax.text(
            x,
            (first + last) / 2,
            label,
            transform=ax.get_yaxis_transform(),
            ha="center",
            va="center",
            rotation=90,
            fontsize=9.5 if numbered and three_line else 12,
            fontweight="bold",
            color="#333333",
        )
        if last < len(hazards) - 1:
            ax.axhline(last + 0.5, color="#eeeeee", linewidth=0.8)


def italicize_bridges_tick(ax: plt.Axes) -> None:
    for label in ax.get_yticklabels():
        if label.get_text() == "Bridges":
            label.set_fontstyle("italic")


def plot_s4_freight_passenger(row: pd.Series, data: pd.DataFrame, data_status: str, components=("Rerouting", "Isolation")) -> plt.Figure:
    colors = {**COST_COLORS, "Operating":"#7fb6da", "Time":"#3a7ca5", "Toll":"#d3e6f3"}
    fig, axes = plt.subplots(1, 2, figsize=(7.48, 4.6), sharex=False)
    for ax, flow in zip(axes, ["Passenger", "Freight"]):
        sub = data[data["flow"].eq(flow)]
        pivot = sub.pivot_table(index="hazard", columns="component", values="cost", aggfunc="sum").reindex(HAZARDS).fillna(0)
        labels = [HAZARD_LABELS.get(hazard, hazard) for hazard in pivot.index]
        stacked_barh(
            ax,
            labels,
            {c: pivot.get(c, 0).to_numpy() for c in components},
            colors,
            legend=False,
        )
        ax.set_title(flow)
        if flow == "Freight":
            ax.tick_params(axis="y", labelleft=False, length=0)
    fig.legend(
        handles=[Patch(color=colors[c], label=c) for c in components],
        loc="lower center",
        ncol=len(components),
        bbox_to_anchor=(0.5, 0.065),
    )
    fig.tight_layout(rect=(0, 0.12, 1, 1))
    fig.text(.5, .095, ("Rerouting cost (millions of dollars, 2023)" if "Isolation" not in components else "Rerouting and isolation cost (millions of dollars, 2023)"),
             ha="center", va="center", fontsize=12, gid="shared-x-label")
    return fig


def plot_state_flow_cost(row: pd.Series, data: pd.DataFrame, data_status: str) -> plt.Figure:
    fig, axes = plt.subplots(2, 2, figsize=(7.48, 5.3), sharex=True)
    for idx, (ax, hazard) in enumerate(zip(axes.ravel(), HAZARDS)):
        sub = data[data["hazard"].eq(hazard)].copy()
        sub["total"] = sub[["Direct", "Rerouting", "Isolation"]].sum(axis=1)
        sub = sub.assign(_rest=sub["state"].eq("Rest")).sort_values(["_rest", "total"], ascending=[True, False]).head(5)
        labels = [wrap_label(v, 13) for v in sub["state"]]
        stacked_barh(
            ax,
            labels,
            {component: sub[component].to_numpy() for component in ["Direct", "Rerouting", "Isolation"]},
            COST_COLORS,
            legend=False,
        )
        ax.set_title(f"({['i', 'ii', 'iii', 'iv'][idx]}) {hazard}", loc="left", fontsize=12, fontweight="bold", color="#333333")
        if idx >= 2:
            ax.set_xlabel("Total cost (billions of dollars, 2023)")
    fig.legend(
        handles=[Patch(color=COST_COLORS[c], label=c) for c in ["Direct", "Rerouting", "Isolation"]],
        loc="lower center",
        ncol=3,
        bbox_to_anchor=(0.5, 0.025),
    )
    fig.tight_layout(rect=(0, 0.075, 1, 1))
    return fig


def affected_cost_metrics(data: pd.DataFrame) -> tuple[pd.DataFrame, list[pd.Series | None]]:
    data = data.copy()
    if "geo_scope" not in data:
        raise ValueError("RQ1c requires geo_scope to identify affected states")
    data = data[data["geo_scope"].eq("affected")]
    totals = data.groupby("hazard")[list(COST_COLORS)].sum().reindex(HAZARDS)
    state_col = "state" if "state" in data else "geo_id"
    normalizers = pd.read_csv(VIZ_DIR / "rq1c_state_normalizers.csv").set_index("state")
    for column in ["lane_miles", "freight_value_dollars"]:
        data[column] = data[state_col].map(normalizers[column])
        if data[column].isna().any():
            raise ValueError(f"Missing state normalizer: {column}")
    population_path = VIZ_DIR / "population_census_2023.csv"
    population = None
    if population_path.exists():
        census = pd.read_csv(population_path, encoding="latin1")
        lookup = census[census["SUMLEV"].eq(40)].set_index("NAME")["POPESTIMATE2023"]
        data["population"] = data[state_col].map(lookup)
        if data["population"].notna().all():
            population = data.drop_duplicates(["hazard", state_col]).groupby("hazard")["population"].sum().reindex(HAZARDS)
    denominators = []
    for column in ["lane_miles", "freight_value_dollars"]:
        denominators.append(data.drop_duplicates(["hazard", state_col]).groupby("hazard")[column].sum().reindex(HAZARDS)
                            if column in data else None)
    return totals, [pd.Series(1., index=HAZARDS), *denominators, population]


def plot_ranked_state_metrics(row: pd.Series, data: pd.DataFrame, data_status: str) -> plt.Figure:
    if data_status != "synthetic":
        totals, denominators = affected_cost_metrics(data)
        numerators = [totals] * 4
    else:  # reconciled placeholders: per-panel numerators and explicit denominators
        metrics = synthetic_model.ranked_metrics()
        numerators, denominators = metrics["numerators"], metrics["denominators"]
    panels = [
        ("(i) Total cost", ("Billions" if SENTENCE_CASE_XLABELS else "billions") + " of dollars, 2023", 1),
        ("(ii) Cost per lane-mile of roadways", "2023 dollars per lane-mile", 1e9),
        ("(iii) Cost relative to annual freight value", "Costs / annual outbound freight value (%)", 1e11),
        ("(iv) Cost per capita", "Dollars (2023) per capita", 1e9),
    ]
    fig, axes = plt.subplots(2, 2, figsize=(10, 6.5))
    fig.set_label("rq1c")
    for idx, (ax, (title, unit, multiplier), denominator) in enumerate(zip(axes.ravel(), panels, denominators)):
        if denominator is None:
            ax.text(.5, .5, "Awaiting model denominator", transform=ax.transAxes, ha="center", va="center")
            ax.set_yticks(range(4), [HAZARD_LABELS[h] for h in HAZARDS] if idx % 2 == 0 else [""]*4)
            ax.set_ylim(3.5, -.5)
            ax.set_xticks([])
        else:
            if denominator.isna().any() or (denominator <= 0).any():
                raise ValueError("Missing or nonpositive normalization denominator")
            values = numerators[idx].mul(multiplier).div(denominator, axis=0)
            stacked_barh(ax, [HAZARD_LABELS[h] for h in HAZARDS],
                         {c: values[c].to_numpy() for c in COST_COLORS}, COST_COLORS, legend=False)
            if idx % 2:
                ax.tick_params(axis="y", labelleft=False)
        ax.set_title(title, loc="left", fontsize=12, fontweight="bold", color="#333333", pad=6)
        ax.set_xlabel(unit)
    fig.legend(handles=[Patch(color=c, label=k) for k,c in COST_COLORS.items()], loc="lower center", ncol=3)
    fig.tight_layout(rect=(0, .07, 1, 1), h_pad=2, w_pad=2)
    return fig


def plot_industry_composition(data: pd.DataFrame) -> plt.Figure:
    totals = data.pivot_table(index="hazard", columns="industry", values="cost", aggfunc="sum").reindex(HAZARDS).fillna(0)
    shares = totals.div(totals.sum(axis=1), axis=0) * 100
    fig, ax = plt.subplots(figsize=(8.5, 4.8))
    values = totals if COMPOSITION_MAGNITUDE else shares
    stacked_barh(ax, [HAZARD_LABELS[h] for h in HAZARDS],
                 {c: values[c].to_numpy() for c in INDUSTRY_COLORS}, INDUSTRY_COLORS, legend=False)
    ax.set_gid("composition")
    if COMPOSITION_MAGNITUDE:
        ax.set_xlabel("Disrupted freight cost (billions of dollars, 2023)")
    else:
        ax.set_xlim(0, 110)
        ax.set_xticks([0,25,50,75,100])
        ax.set_xlabel("Share of disrupted freight cost (%)")
    fig.legend(handles=[Patch(color=c,label=k) for k,c in INDUSTRY_COLORS.items()], ncol=3, loc="lower center")
    fig.tight_layout(rect=(0,.08,1,1))
    return fig


def plot_generic(row: pd.Series, data: pd.DataFrame, data_status: str) -> plt.Figure:
    row_id = row["id"]

    if row_id == "x_freight_commodity_delta":
        return plot_industry_composition(data)
    if row_id == "s4_freight_passenger_rerouting_isolation":
        return plot_s4_freight_passenger(row, data, data_status)
    if row_id == "x_sankey_cost_flow_state":
        return plot_state_flow_cost(row, data, data_status)
    if row_id == "x_ranked_states_4metric":
        return plot_ranked_state_metrics(row, data, data_status)

    fig, ax = plt.subplots(figsize=(7.48, 4.8))

    if row_id == "s3_major_cost_panel_a_facility":
        data = data.assign(
            _hazard=pd.Categorical(data["hazard"], categories=HAZARDS, ordered=True),
            _bridge=data["facility_type"].eq("Bridges"),
            _total=data[list(SEVERITY_COLORS)].sum(axis=1),
        ).sort_values(["_hazard", "_total"], ascending=[True, False])
        labels = list(data["facility_type"])
        fig.set_size_inches(7.48, 8.4)
        stacked_barh(ax, labels, {c: data[c].to_numpy() for c in SEVERITY_COLORS}, SEVERITY_COLORS)
        ax.set_xlim(0, 4.0)
        ax.set_xticks(np.arange(0, 4.01, 0.5))
        ax.set_yticks(np.arange(len(data)), labels)
        ax.set_xlabel("Direct infrastructure damage cost (billions of dollars, 2023)")
        grouped_hazard_labels(ax, data["hazard"], x=-0.18, numbered=NUMBER_GROUPS)
        italicize_bridges_tick(ax)
        fig.subplots_adjust(left=0.25)

    elif row_id == "s3_major_cost_panel_b_state":
        label_col = "state" if "state" in data.columns else "geo_id"
        top = data.sort_values(["hazard", "Direct"], ascending=[True, False]).groupby("hazard").head(3)
        labels = [wrap_label(s, 16) for s in top[label_col]]
        fig.set_size_inches(7.48, 4.9)
        y = np.arange(len(top))
        ax.barh(y, top["Direct"], color=[HAZARD_COLORS[h] for h in top["hazard"]], height=0.66)
        ax.errorbar(top["Direct"], y, xerr=top["Direct_error"], fmt="none", ecolor="#333333", elinewidth=0.8, capsize=2)
        for yi, (value, error) in enumerate(zip(top["Direct"], top["Direct_error"])):
            ax.annotate(f"{value:,.2f}", (value + error, yi), xytext=(9, 0),
                        textcoords="offset points", va="center", fontsize=12, color="#777777")
        ax.set_xlim(0, (top["Direct"] + top["Direct_error"]).max() * 1.16)
        ax.set_xlabel("Direct infrastructure damage cost, mean with min–max range (billions of dollars, 2023)")
        ax.set_yticks(y, labels)
        ax.invert_yaxis()
        grouped_hazard_labels(ax, top["hazard"], x=-0.18, three_line=True, numbered=NUMBER_GROUPS)
        fig.subplots_adjust(left=0.25)

    elif row_id == "s4_rerouting_components":
        pivot = data.pivot_table(index="hazard", columns="component", values="cost", aggfunc="sum").reindex(HAZARDS).fillna(0)
        colors = {"Time": "#3a7ca5", "Operate": "#7fb6da", "Toll": "#d3e6f3"}
        stacked_barh(ax, [HAZARD_LABELS.get(h, h) for h in pivot.index], {c: pivot[c].to_numpy() for c in pivot.columns}, colors)
        ax.set_xlabel("Rerouting cost (millions of dollars, 2023)")
        handles, labels = ax.get_legend_handles_labels()
        ax.legend(handles, ["Operating" if label == "Operate" else label for label in labels],
                  loc="upper center", bbox_to_anchor=(0.5, -0.085), ncol=3)

    elif row_id == "x_state_topN_coverage_table":
        for hazard in HAZARDS:
            sub = data[data["hazard"].eq(hazard)]
            ax.plot(sub["coverage_pct"], sub["N"], marker="o", color=HAZARD_COLORS[hazard], label=hazard)
        ax.set_xlabel("Hazard total captured by top-N geos (%)")
        ax.set_ylabel("N (states)")
        ax.legend(loc="lower right")

    elif row_id == "x_freight_commodity_delta":
        data["label"] = data["hazard"] + " - " + data["commodity"]
        colors = [HAZARD_COLORS[h] if v >= 0 else "#b7b7b7" for h, v in zip(data["hazard"], data["delta"])]
        ax.barh(np.arange(len(data)), data["delta"], color=colors, height=0.66)
        ax.axvline(0, color="#333333", linewidth=0.8)
        ax.set_yticks(np.arange(len(data)), [wrap_label(v, 24) for v in data["label"]])
        ax.invert_yaxis()
        ax.set_xlabel("Disrupted freight share minus affected-state output share (percentage points)")

    elif row_id == "x_top5_states_industry":
        grouped = data.groupby(["hazard", "state", "industry"], as_index=False)["cost"].sum()
        totals = grouped.groupby(["hazard", "state"], as_index=False)["cost"].sum()
        keep = (totals.assign(_rest=totals["state"].eq("Rest")).sort_values(["hazard", "_rest", "cost"], ascending=[True, True, False])
                .groupby("hazard").head(5)[["hazard", "state"]])
        top = grouped.merge(keep, on=["hazard", "state"])
        labels_df = keep.reset_index(drop=True)
        labels = [wrap_label(s, 16) for s in labels_df["state"]]
        fig.set_size_inches(7.48, 8.4)
        arrays = {}
        for industry in INDUSTRY_COLORS:
            arrays[industry] = [
                float(top[(top["hazard"].eq(h)) & (top["state"].eq(s)) & (top["industry"].eq(industry))]["cost"].sum())
                for h, s in zip(labels_df["hazard"], labels_df["state"])
            ]
        stacked_barh(ax, labels, {k: np.asarray(v) for k, v in arrays.items()}, INDUSTRY_COLORS, legend=False)
        ax.set_xlabel("Cargo value of disrupted freight (billions of dollars, 2023)", labelpad=6)
        grouped_hazard_labels(ax, labels_df["hazard"], x=-0.18, numbered=NUMBER_GROUPS)
        fig.legend(
            handles=[Patch(color=color, label=label) for label, color in INDUSTRY_COLORS.items()],
            loc="lower center",
            ncol=3,
            bbox_to_anchor=(0.5, 0.015),
        )

    else:
        if "Direct" in data.columns:
            data["value"] = data[["Direct", "Rerouting", "Isolation"]].sum(axis=1)
        elif "cost" in data.columns:
            data["value"] = data["cost"]
        elif "coverage_pct" in data.columns:
            data["value"] = data["coverage_pct"]
        else:
            numeric_cols = list(data.select_dtypes(include=[np.number]).columns)
            data["value"] = data[numeric_cols[0]] if numeric_cols else np.arange(len(data))
        labels = data.iloc[:, 0].astype(str).head(12).tolist()
        vals = data["value"].head(12).to_numpy()
        ax.barh(np.arange(len(vals)), vals, color="#3d4d5c", height=0.66)
        ax.set_yticks(np.arange(len(vals)), [wrap_label(v, 24) for v in labels])
        ax.invert_yaxis()
        ax.set_xlabel(str(row["x_dim"]))

    if row_id == "x_top5_states_industry":
        fig.tight_layout(rect=(0, 0.09, 1, 1))
    else:
        fig.tight_layout()
    return fig


def caveat_status(row: pd.Series) -> tuple[str, str]:
    if row["id"] == "x_ranked_states_4metric":
        return "All affected-state rows aggregated; same numerator; Census 2023 population", "Model lane-miles; annual outbound freight value is a baseline proxy, not disrupted cargo value. Costs and affected-state membership remain illustrative."
    if row["id"] == "x_freight_commodity_delta":
        return "Industry cost shares sum to 100%; same source as RQ3b before top-N selection", "Synthetic layout data; not evidence of industry vulnerability"
    caveats = str(row.get("caveats", "")).strip()
    resolved = ["registry fields used literally", "vector PDF exported"]
    open_items = caveats or "none"
    if row["id"] == "s3_major_cost_panel_a_facility":
        resolved.extend(["hazard x facility y-axis used", "no carriageway type invented", "severity used as stacked color dimension"])
        open_items = "none"
    if row["id"] == "s3_major_cost_panel_b_state":
        resolved.append("affected-state top-N layout rendered")
        open_items = "top-10 N still advisory; layout currently uses compact top-3 preview"
    if row["id"] == "s4_freight_passenger_rerouting_isolation":
        resolved.append("2-line wrapped y-labels applied")
        open_items = "none"
    if row["id"] == "x_freight_commodity_delta":
        resolved.append("compares disrupted freight mix with affected-state output mix; negative deltas use gray, not red")
        open_items = "premise still needs a caption-level reason to keep it in the main set"
    if row["id"] == "x_top5_states_industry":
        resolved.append("all five repository SCTG groups represented")
        open_items = "none"
    if row["id"] == "x_sankey_cost_flow_state":
        return "; ".join(resolved), "N for top-N states not finalized; clean small-multiple fallback rendered while Sankey layout remains deferred"
    if open_items != "none":
        return "; ".join(resolved), open_items
    return "; ".join(resolved), "none"


def write_contact_sheet(records: list[BuildRecord]) -> None:
    groups = {rq: [r for r in records if r.rq_group == rq] for rq in ["RQ1", "RQ2", "RQ3"]}
    sections = []
    for rq, rows in groups.items():
        cards = []
        for record in rows:
            png_rel = Path(record.png).relative_to(OUT_DIR).as_posix()
            pdf_rel = Path(record.pdf).relative_to(OUT_DIR).as_posix()
            display_name = Path(record.pdf).stem
            cards.append(
                f"""
                <article class="card">
                  <a href="{html.escape(pdf_rel)}"><img src="{html.escape(png_rel)}" alt="{html.escape(record.row_id)}"></a>
                  <div class="body">
                    <h3>{html.escape(display_name)}</h3>
                    <p><a href="{html.escape(pdf_rel)}">PDF</a></p>
                  </div>
                </article>
                """
            )
        sections.append(f"<section><h2>{rq}</h2><div class=\"grid\">{''.join(cards)}</div></section>")
    html_doc = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Advisor review figures by RQ</title>
<style>
body {{ font-family: Arial, DejaVu Sans, sans-serif; margin: 24px 32px 64px; color: #1a1a1a; background: #fafafa; }}
h1 {{ margin-bottom: 4px; }}
.subtitle {{ color: #555; margin-bottom: 24px; }}
h2 {{ margin-top: 32px; border-bottom: 1px solid #ddd; padding-bottom: 6px; }}
.grid {{ display: grid; grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); gap: 20px; }}
.card {{ background: white; border: 1px solid #ddd; border-radius: 6px; overflow: hidden; }}
.card img {{ display: block; width: 100%; border-bottom: 1px solid #eee; }}
.body {{ padding: 10px 12px 14px; }}
.body h3 {{ font-size: 14px; margin: 0 0 4px; }}
.body p {{ font-size: 12px; color: #555; margin: 4px 0; }}
a {{ color: #245f9f; }}
</style>
</head>
<body>
<h1>Advisor review figures by RQ</h1>
<div class="subtitle">Generated from visual_registry.csv. Table-only registry rows are excluded from this figure packet.</div>
{''.join(sections)}
</body>
</html>
"""
    (OUT_DIR / "index.html").write_text(html_doc, encoding="utf-8")


def write_report(records: list[BuildRecord]) -> None:
    report_fields = list(BuildRecord.__dataclass_fields__)
    with (OUT_DIR / "build_report.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=report_fields)
        writer.writeheader()
        for record in records:
            writer.writerow({field: getattr(record, field) for field in report_fields})

    lines = ["# Advisor Review Figure Build Report", ""]
    for record in records:
        lines.extend(
            [
                f"## {record.row_id}",
                "",
                f"- RQ: {record.rq_tag} -> {record.rq_group}",
                f"- Data: {record.data_status}",
                f"- Resolved caveats: {record.resolved_caveats}",
                f"- Open caveats: {record.open_caveats}",
                f"- Output: `{Path(record.pdf).relative_to(OUT_DIR).as_posix()}`",
                "",
            ]
        )
    (OUT_DIR / "build_report.md").write_text("\n".join(lines), encoding="utf-8")


def crop_image_whitespace(image: np.ndarray, tolerance: int = 248, pad: int = 10) -> np.ndarray:
    pixels = image[..., :3]
    if image.shape[-1] == 4:
        visible = image[..., 3] > 0.02
        nonwhite = visible & np.any(pixels < tolerance / 255, axis=2)
    else:
        nonwhite = np.any(pixels < tolerance / 255, axis=2)
    if not np.any(nonwhite):
        return image
    rows, cols = np.where(nonwhite)
    y0 = max(int(rows.min()) - pad, 0)
    y1 = min(int(rows.max()) + pad + 1, image.shape[0])
    x0 = max(int(cols.min()) - pad, 0)
    x1 = min(int(cols.max()) + pad + 1, image.shape[1])
    return image[y0:y1, x0:x1]


def write_combined_rq_pages(records: list[BuildRecord]) -> None:
    from pypdf import PdfReader, PdfWriter, Transformation

    for rq in ["RQ1", "RQ2", "RQ3"]:
        group = [record for record in records if record.rq_group == rq]
        if not group:
            continue
        pages = [PdfReader(record.pdf).pages[0] for record in group]
        # Two tall figures above a wide figure; scale uniformly in both directions.
        margin, gap, label_height = 18.0, 18.0, 18.0
        layout = json.loads((VIZ_DIR / "sheet_layout.json").read_text())
        rows = [[ord(letter)-ord('a') for letter in row] for row in layout[rq]]
        if sorted(i for row in rows for i in row) != list(range(len(group))):
            raise ValueError(f"{rq}: layout must include each panel exactly once")
        width = max(sum(float(pages[i].mediabox.width) for i in row) + gap*(len(row)-1) for row in rows) + 2*margin
        placements = []
        top = margin
        for indices in rows:
            slot = (width - 2 * margin - gap * (len(indices) - 1)) / len(indices)
            scales = [1.0 for i in indices]
            heights = [float(pages[i].mediabox.height) * scale for i, scale in zip(indices, scales)]
            for col, (i, scale, height) in enumerate(zip(indices, scales, heights)):
                placements.append((i, margin + sum(float(pages[j].mediabox.width) for j in indices[:col]) + col*gap, top + label_height, scale, height))
            top += label_height + max(heights) + gap
        height = top - gap + margin
        writer = PdfWriter()
        sheet = writer.add_blank_page(width=width, height=height)
        preview = plt.figure(figsize=(width/72, height/72))
        overlay = plt.figure(figsize=(width/72, height/72))
        for i, x, top_y, scale, panel_height in placements:
            page = pages[i]
            y = height - top_y - panel_height
            panel_width = float(page.mediabox.width) * scale
            sheet.merge_transformed_page(page, Transformation().scale(scale).translate(x, y))
            ax = preview.add_axes((x/width, y/height, panel_width/width, panel_height/height))
            ax.imshow(plt.imread(group[i].png), aspect="equal")
            ax.axis("off")
            label_x = (x + group[i].axis_x * scale)/width
            label_y = (height - top_y + 4)/height
            for fig in (preview, overlay):
                fig.text(label_x, label_y, chr(ord('a') + i), ha="left", va="bottom",
                         fontsize=12, fontweight="bold")
        buffer = BytesIO()
        overlay.savefig(buffer, format="pdf")
        buffer.seek(0)
        sheet.merge_page(PdfReader(buffer).pages[0])
        with (OUT_DIR / f"{rq}_combined_review_sheet.pdf").open("wb") as output:
            writer.write(output)
        preview.savefig(OUT_DIR / f"{rq}_combined_review_sheet.png", dpi=150)
        plt.close(preview)
        plt.close(overlay)


def main() -> None:
    apply_style()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = filtered_rows(load_registry())
    records: list[BuildRecord] = []
    for _, row in rows.iterrows():
        data, status = load_or_synthetic(row)
        data_status = "synthetic" if status == "synthetic" else status
        fig = plot_generic(row, data, data_status)
        pdf, png, axis_x = save_figure(fig, row)
        resolved, open_items = caveat_status(row)
        records.append(
            BuildRecord(
                row_id=row["id"],
                rq_group=row["rq_group"],
                rq_tag=row["rq_tag"],
                chart_type=row["chart_type"],
                data_status=data_status,
                pdf=str(pdf),
                png=str(png),
                axis_x=axis_x,
                resolved_caveats=resolved,
                open_caveats=open_items,
            )
        )
    write_contact_sheet(records)
    write_report(records)
    write_combined_rq_pages(records)
    print(f"Built {len(records)} advisor-review rows into {OUT_DIR}")


if __name__ == "__main__":
    main()

