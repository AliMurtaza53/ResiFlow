"""Run every Sioux Falls hazard and event through the pipeline and tabulate what comes out.

The multihazard pytest only checks that files exist. This script runs scripts 2, 3 and 4 for each hazard (flood surface,
river, coastal, earthquake, landslide, winter storm) and event (0 miss, 1 bridge bottleneck, 3 disconnect stress), then
reads the outputs: links with intensity, links closed, direct damage by asset type (bridge/tunnel once per link, roads
summed), and the rerouting cost matrix. Failures are recorded with the script's stderr tail, not hidden.

Usage (needs the full model environment, e.g. the Hopper `nird` env; do NOT export RESIFLOW_CONFIG_PATH/NIRD_CONFIG_PATH):
    python scripts/diagnostics/inspect_multihazard_sioux_falls.py --out /scratch/.../mh_inspect
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[2]
for p in (REPO_ROOT / "tests", REPO_ROOT / "src", REPO_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from multihazard_sioux_falls_fixtures import (  # noqa: E402
    build_multihazard_dataset,
    multihazard_env,
    scenario_for,
)
from toy_pipeline_fixtures import damage_dir, disruption_dir, reroute_dir, run_script  # noqa: E402

from resiflow import damage_aggregation as da  # noqa: E402

CASES = [
    ("flood", "flood_surface"),
    ("flood", "flood_river"),
    ("flood", "flood_coastal"),
    ("earthquake", None),
    ("landslide", None),
    ("winter_storm", None),
]
EVENTS = ["0", "1", "3", "4", "5", "6"]  # 0 miss, 1 bridge, 3 disconnect, 4 low, 5 high, 6 extreme (intensity ladder)

# Time-dependent variants. Each is a parameter-override patch (RESIFLOW_PARAM_OVERRIDES file). "default" keeps the toy
# one-row recovery table; the others switch on the real T26 bridge/road schedules (0 -> 50% -> 100% capacity over days)
# and the T37/T38 residual-speed scenarios, or change the T34 winter region (reopening days x region factor).
VARIANTS = {
    "default": {},
    "recovery_fast": {"recovery": {"use_table_recovery_design": True, "table_recovery_scenario": "fast"}},
    "recovery_average": {"recovery": {"use_table_recovery_design": True, "table_recovery_scenario": "average"}},
    "recovery_slow": {"recovery": {"use_table_recovery_design": True, "table_recovery_scenario": "slow"}},
    "winter_region_high": {"hazard_disruption": {"winter_storm_snow_region": "high_capability"}},
    "winter_region_low": {"hazard_disruption": {"winter_storm_snow_region": "low_capability"}},
}
# Variants only meaningful for some hazards (avoid wasted runs).
VARIANT_HAZARDS = {
    "winter_region_high": {"winter_storm"},
    "winter_region_low": {"winter_storm"},
}


def _numeric_sums(df: pd.DataFrame) -> dict:
    return {c: round(float(pd.to_numeric(df[c], errors="coerce").sum()), 4) for c in df.columns if pd.api.types.is_numeric_dtype(df[c])}


def inspect_case(tmp: Path, base_env: dict, hazard: str, subtype: str | None, event: str) -> dict:
    row = {"hazard": subtype or hazard, "event": event, "status": "ok", "error": ""}
    env = multihazard_env(tmp, Path(base_env["NIRD_CONFIG_PATH"]), hazard_type=hazard, flood_subtype=subtype)
    try:
        scenario = scenario_for(hazard, flood_subtype=subtype, event_id=event)
    except Exception as exc:  # no registered scenario
        row.update(status="no_scenario", error=str(exc)[:200])
        return row
    sp = scenario.scenario_param
    row["scenario_param"] = sp
    for script, args in (
        ("2_intersection_analysis.py", [str(sp), event]),
        ("3_damage_analysis.py", []),
        ("4_rerouting_and_recovery_scenario_loop.py", [str(sp), event, "1", "1"]),
    ):
        try:
            run_script(script, args, env)
        except subprocess.CalledProcessError as exc:
            row.update(status=f"FAILED {script}", error=(exc.stderr or "")[-600:].replace("\n", " | "))
            break

    links_path = disruption_dir(tmp, base_env, depth_key=sp) / "links" / f"road_links_{event}.gpq"
    if links_path.exists():
        links = pd.read_parquet(links_path)
        row["links"] = len(links)
        inten = links["intensity_primary"] if "intensity_primary" in links.columns else links.get("flood_depth_max", pd.Series(0.0, index=links.index))
        inten = pd.to_numeric(inten, errors="coerce").fillna(0.0)
        row["links_with_intensity"] = int((inten > 0).sum())
        row["max_intensity"] = float(inten.max())
        if "max_speed" in links.columns:
            row["links_closed"] = int((pd.to_numeric(links["max_speed"], errors="coerce") == 0).sum())
        if "max_speed" in links.columns and "free_flow_speeds" in links.columns:
            ms = pd.to_numeric(links["max_speed"], errors="coerce")
            ff = pd.to_numeric(links["free_flow_speeds"], errors="coerce")
            row["links_slowed"] = int((ms < ff - 1e-9).sum())  # includes closed; partial reductions are not closures
        if "day_open" in links.columns:
            do = pd.to_numeric(links["day_open"], errors="coerce").fillna(0)
            row["links_day_open_gt0"] = int((do > 0).sum())  # winter storm: closed until T34 day_open
            row["max_day_open"] = int(do.max())
        if "road_label" in links.columns:
            hit = links.loc[inten > 0, "road_label"].astype(str).value_counts().to_dict()
            row["hit_by_label"] = json.dumps(hit)
    else:
        row["links"] = "missing"

    dmg_files = sorted(damage_dir(tmp, base_env, scenario_param=sp).glob(f"*_{event}_with_damage_values.csv")) or sorted(
        damage_dir(tmp, base_env, scenario_param=sp).glob("*with_damage_values.csv")
    )
    if dmg_files:
        d = pd.read_csv(dmg_files[0], low_memory=False)
        row["damage_rows"] = len(d)
        row["raw_usd_sum"] = float(pd.to_numeric(d.get("direct_damage_mean_usd", pd.Series(dtype=float)), errors="coerce").sum())
        row["damage_file"] = dmg_files[0].name
        if len(d) and "direct_damage_mean_usd" in d.columns:
            d = da.add_consolidated_damage_columns(d) if hasattr(da, "add_consolidated_damage_columns") else d
            row["direct_musd"] = round(float(da.total_direct_damage_musd(d)), 6)
            if "road_label" in d.columns and "e_id" in d.columns:
                by = {}
                for lab, g in d.groupby(d["road_label"].astype(str)):
                    by[lab] = round(float(da.total_direct_damage_musd(g)), 6)
                row["direct_musd_by_label"] = json.dumps(by)
        else:
            row["direct_musd"] = 0.0
    else:
        row["damage_rows"] = "no file"

    cm = reroute_dir(tmp, base_env, depth_key=sp, event_key=int(event)) / "cost_matrix_by_scenario.csv"
    if cm.exists():
        c = pd.read_csv(cm)
        row["reroute_columns_sum"] = json.dumps(_numeric_sums(c))
        row["event_days"] = json.dumps(sorted(set(int(x) for x in c["event_day"].dropna()))) if "event_day" in c.columns else "n/a"
        if "event_day" in c.columns:
            ts = c.groupby("event_day").sum(numeric_only=True).reset_index()
            ts.insert(0, "event", event)
            ts.insert(0, "hazard", subtype or hazard)
            row["_timeseries"] = ts
    else:
        row["reroute_columns_sum"] = "no file"
    return row


def run_variant(out: Path, variant: str, hazards: set, events: list) -> tuple[list, list]:
    """Fresh dataset and run per variant: results folders are keyed by scenario and event, so variants must not share one."""
    tmp = out / variant
    tmp.mkdir(parents=True, exist_ok=True)
    overrides = VARIANTS[variant]
    if overrides:
        path = tmp / "param_overrides.json"
        path.write_text(json.dumps(overrides), encoding="utf-8")
        os.environ["RESIFLOW_PARAM_OVERRIDES"] = str(path)
    else:
        os.environ.pop("RESIFLOW_PARAM_OVERRIDES", None)
    config_path, _ = build_multihazard_dataset(tmp)
    base_env = multihazard_env(tmp, config_path, hazard_type="flood", flood_subtype="flood_surface")
    base_env.update({k: v for k, v in os.environ.items() if k == "RESIFLOW_PARAM_OVERRIDES"})
    run_script("1_network_flow_model_revision.py", ["1", "1"], base_env)
    only = VARIANT_HAZARDS.get(variant)
    rows, series = [], []
    for h, sub in CASES:
        name = sub or h
        if (hazards and name not in hazards) or (only and h not in only):
            continue
        for e in events:
            env_row = inspect_case(tmp, base_env, h, sub, e)
            env_row["variant"] = variant
            ts = env_row.pop("_timeseries", None)
            if ts is not None:
                ts.insert(0, "variant", variant)
                series.append(ts)
            rows.append(env_row)
    return rows, series


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--hazards", default="", help="comma list of case names to run (default all), e.g. flood_surface,earthquake")
    ap.add_argument("--events", default="", help="comma list of events (default 0,1,3,4,5,6)")
    ap.add_argument("--variants", default="default", help=f"comma list from {sorted(VARIANTS)}, or 'all'")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    hazards = {x for x in args.hazards.split(",") if x}
    events = [x for x in args.events.split(",") if x] or EVENTS
    names = sorted(VARIANTS) if args.variants == "all" else [x for x in args.variants.split(",") if x]
    rows, series = [], []
    for v in names:
        r, t = run_variant(args.out, v, hazards, events)
        rows += r
        series += t
    table = pd.DataFrame(rows)
    table.to_csv(args.out / "multihazard_inspection.csv", index=False)
    if series:
        pd.concat(series, ignore_index=True).to_csv(args.out / "recovery_timeseries.csv", index=False)
    with pd.option_context("display.max_colwidth", 120, "display.width", 250):
        print(table.drop(columns=["error"]).to_string(index=False))
        for r in rows:
            if r["error"]:
                print(f"{chr(10)}ERROR {r['variant']} {r['hazard']} event {r['event']}: {r['error']}")


if __name__ == "__main__":
    main()
