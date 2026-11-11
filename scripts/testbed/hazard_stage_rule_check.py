"""Does Script 4's per-OD disruption rule see partial capacity loss?

Runs the Anaheim baseline (default 20x demand), damages the 10 most loaded links to 50% / 25% / 0% of
capacity, and compares (a) the flow the Script 4 rule would flag, replicated from
``scripts/4_rerouting_and_recovery_scenario_loop.py`` (per path row: ``flow - min damaged capacity``,
floored at 0) with (b) the link-load excess (load minus damaged capacity). The rule is replicated, not
executed through Script 4.

Usage: python scripts/testbed/hazard_stage_rule_check.py --out <dir> [--demand-scale 20]
"""
import argparse, importlib.util
from pathlib import Path
import duckdb, numpy as np, pandas as pd
ap = argparse.ArgumentParser(); ap.add_argument("--out", type=Path, required=True); ap.add_argument("--demand-scale", type=float, default=20.0)
args = ap.parse_args()
spec = importlib.util.spec_from_file_location("rep", Path(__file__).with_name("assignment_debug_report.py"))
rep = importlib.util.module_from_spec(spec); spec.loader.exec_module(rep)
out = args.out
cap = rep.run_observed("anaheim", args.demand_scale, out)
links = cap["links"][["e_id", "acc_flow", "current_capacity"]].set_index("e_id")
rows = duckdb.connect(str(out / "assignment.duckdb")).execute("SELECT origin, destination, path, flow FROM odpfc").df()
rows["path"] = rows["path"].apply(list)
hot = links.sort_values("acc_flow", ascending=False).head(10).index
print(f"damaging the 10 most loaded links; their baseline V/C: {np.round((links.loc[hot,'acc_flow']/links.loc[hot,'current_capacity']).values,2)}")
ex = rows[["flow", "path"]].explode("path").rename(columns={"path": "e_id"})
load = ex.groupby("e_id")["flow"].sum()
for keep in (0.5, 0.25, 0.0):
    dcap = (links.loc[hot, "current_capacity"] * keep)
    # Script 4 rule: per path-row, flow minus the MIN damaged capacity over its damaged links, floored at 0
    on = rows[rows["path"].apply(lambda p: any(e in dcap.index for e in p))].copy()
    on["mincap"] = on["path"].apply(lambda p: min(dcap[e] for e in p if e in dcap.index))
    on["flag"] = (on["flow"] - on["mincap"]).clip(lower=0)
    flagged_rule = on["flag"].sum()
    excess = (load.reindex(dcap.index).fillna(0) - dcap).clip(lower=0)
    flagged_links = set(e for p, f in zip(on["path"], on["flag"]) if f > 0 for e in p if e in dcap.index)
    over = excess[excess > 0].index
    missed = [e for e in over if e not in flagged_links]
    print(f"keep {keep:>4.0%}: link-load excess (sum over damaged links)={excess.sum():>10.0f} | rule-flagged flow={flagged_rule:>10.0f} | "
          f"overloaded damaged links={len(over)}, of which no path flagged={len(missed)}")
