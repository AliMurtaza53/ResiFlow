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
EVENTS = ["0", "1", "3"]


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
    else:
        row["reroute_columns_sum"] = "no file"
    return row


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    tmp = args.out
    tmp.mkdir(parents=True, exist_ok=True)
    config_path, _ = build_multihazard_dataset(tmp)
    base_env = multihazard_env(tmp, config_path, hazard_type="flood", flood_subtype="flood_surface")
    run_script("1_network_flow_model_revision.py", ["1", "1"], base_env)
    rows = [inspect_case(tmp, base_env, h, s, e) for h, s in CASES for e in EVENTS]
    table = pd.DataFrame(rows)
    table.to_csv(tmp / "multihazard_inspection.csv", index=False)
    with pd.option_context("display.max_colwidth", 120, "display.width", 250):
        print(table.drop(columns=["error"]).to_string(index=False))
        for r in rows:
            if r["error"]:
                print(f"\nERROR {r['hazard']} event {r['event']}: {r['error']}")


if __name__ == "__main__":
    main()
