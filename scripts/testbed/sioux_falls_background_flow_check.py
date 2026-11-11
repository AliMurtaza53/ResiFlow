"""Is baseline (background) flow carried into the rerouting stage?  Sioux Falls, full Script 1-4 chain.

Runs the pipeline fixture at ``--scale`` x the default demand scale, then reports (1) what the disruption
stage kept from the baseline link table (``current_flow``, ``current_capacity`` vs ``acc_flow``,
``acc_capacity``) and (2) how many links would exceed physical capacity if background flow were added back
to the rerouted flow (``baseline - released + rerouted``; capacity is the undamaged physical capacity).

Usage: python scripts/testbed/sioux_falls_background_flow_check.py --out <dir> [--scale 3]
"""
import argparse, shutil, sys
from pathlib import Path

import geopandas as gpd
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
import sioux_falls_fixtures as F  # noqa: E402
from toy_pipeline_fixtures import base_scenario_dir, disruption_dir, reroute_dir, run_pipeline_scripts  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--out", type=Path, required=True)
ap.add_argument("--scale", type=float, default=1.0, help="multiplier on the fixture demand scale")
args = ap.parse_args()
F.DEMAND_SCALE = F.DEMAND_SCALE * args.scale
root = args.out
shutil.rmtree(root, ignore_errors=True)
root.mkdir(parents=True)
cfg, _, _ = F.build_sioux_falls_dataset(root)
env = F.sioux_falls_env(root, cfg)
run_pipeline_scripts(env)

b = pd.read_parquet(base_scenario_dir(root, env) / "edge_flows.gpq")
d = gpd.read_parquet(disruption_dir(root, env) / "links" / "road_links_1.gpq")
print(f"baseline table: acc_flow sum={b.acc_flow.sum():.0f}, current_flow sum={b.current_flow.sum():.0f}, "
      f"acc_capacity sum={b.acc_capacity.sum():.0f}, current_capacity sum={b.current_capacity.sum():.0f}")
print(f"disruption-stage table: current_flow sum={d.current_flow.sum():.0f}, current_capacity sum={d.current_capacity.sum():.0f}")
p = pd.read_parquet(next(reroute_dir(root, env).glob("edge_flows_freight_s1_day0.gpq")))
b["vc"] = b.acc_flow / b.current_capacity
print(f"baseline V/C: max={b.vc.max():.2f}, links>0.8={int((b.vc > 0.8).sum())}/{len(b)}")
m = b[["e_id", "acc_flow", "current_capacity"]].merge(p[["e_id", "change_flow", "disrupted_flow"]], on="e_id")
rer = m.change_flow.clip(lower=0)
over = (m.acc_flow - m.disrupted_flow + rer - m.current_capacity).clip(lower=0)
print(f"links over physical capacity with background added back: {int((over > 1e-6).sum())}; total excess flow={over.sum():.0f}; rerouted flow={rer.sum():.0f}")
