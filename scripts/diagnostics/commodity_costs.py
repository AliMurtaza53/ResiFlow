"""Split Stage 4 freight isolation and rerouting cost by commodity group (sctgG5), per run, event and recovery day.

Why this is exact: the assignment is commodity-blind and isolation is a flat cost per isolated truck, so a pair's cost is
shared across commodities in proportion to that pair's commodity mix in the frozen OD (commodity_od.pq, gate-verified).

Per (run, event, day) for the freight class:
  isolation_cost[k]  = class isolation cost (cost matrix) * sum_od(iso_flow_od * share_k(od)) / sum_od(iso_flow_od)
  rerouting_cost[k]  = class rerouting cost (cost matrix) * sum_od(w_od * share_k(od)) / sum_od(w_od), where
                       w_od = post_od - pre_od from the event and baseline odpfc files (flow * (operating+time+toll)).
  The raw sum_od(w_od) is reported next to the cost-matrix rerouting cost (reconciliation); the cost-matrix class total
  is the number that is split, so commodity rows always add up to the class total used elsewhere.
Writes one long CSV: run_id, event, day, class, sctgG5, metric, value, unit, recon_ratio.
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

KEYS = ["origin_node", "destination_node"]
GROUPS = ["sctg0109", "sctg1014", "sctg1519", "sctg2033", "sctg3499"]
DAYS = [0, 7, 14, 30, 60, 90]
R = Path("/scratch/akothaw/multimodal_hazard_data/results/rerouting_analysis")


def share_table(path: Path) -> pd.DataFrame:
    od = pd.read_parquet(path)
    wide = od.pivot_table(index=KEYS, columns="sctgG5", values="Car21", aggfunc="sum", fill_value=0.0)
    wide = wide.reindex(columns=GROUPS, fill_value=0.0)
    tot = wide.sum(axis=1)
    sh = wide.div(tot, axis=0).astype("float64")
    sh.columns = [f"s_{g}" for g in GROUPS]
    return sh


def attach(df: pd.DataFrame, sh: pd.DataFrame) -> pd.DataFrame:
    df = df.astype({k: "int64" for k in KEYS})
    m = df.merge(sh, left_on=KEYS, right_index=True, how="left")
    return m


def od_cost(path: Path) -> pd.DataFrame:
    cols = KEYS + ["flow", "operating_cost_per_flow", "time_cost_per_flow", "toll_cost_per_flow"]
    d = pq.read_table(path, columns=cols).to_pandas()
    d["cost"] = d.flow * (d.operating_cost_per_flow + d.time_cost_per_flow + d.toll_cost_per_flow)
    return d.groupby(KEYS, as_index=False).cost.sum().astype({k: "int64" for k in KEYS})


def split(weights: pd.DataFrame, wcol: str, total: float):
    """weights has share columns s_<group>; returns (per-group value list, share of weight unallocated, raw sum)."""
    w = weights[wcol].to_numpy()
    raw = float(w.sum())
    s = weights[[f"s_{g}" for g in GROUPS]].to_numpy()
    allocated = np.nan_to_num(s) * w[:, None]
    per_group = allocated.sum(axis=0)
    unalloc = float(w[np.isnan(s).any(axis=1)].sum())
    denom = raw if raw != 0 else np.nan
    return (total * per_group / denom if denom == denom else np.zeros(len(GROUPS))), unalloc, raw


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shares", type=Path, required=True, help="commodity_od.pq from commodity_sum_gate.py")
    ap.add_argument("--runs", nargs="+", required=True, help="e.g. freight_304 combined_304")
    ap.add_argument("--out", type=Path, required=True)
    a = ap.parse_args()
    sh = share_table(a.shares)
    rows = []
    for run in a.runs:
        case, ev = run.split("_")
        run_id = f"finalA_{case}_{ev}"
        d = R / run_id / ev / "1"
        cm = d / "cost_matrix_freight_by_scenario.csv"
        if not cm.exists():
            print("skip (no freight cost matrix)", run_id)
            continue
        m = pd.read_csv(cm).set_index("event_day")
        for day in DAYS:
            if day not in m.index:
                continue
            iso_total = float(m.loc[day, "isolation_cost"])
            rer_total = float(m.loc[day, "rerouting_cost"])
            # isolation
            ip = d / f"trip_isolations_freight_s1_day{day}.csv"
            if ip.exists() and iso_total != 0:
                iso = attach(pd.read_csv(ip, usecols=KEYS + ["Car21"]), sh).rename(columns={"Car21": "w"})
                vals, unalloc, raw = split(iso, "w", iso_total)
                for g, v in zip(GROUPS, vals):
                    rows.append((run_id, ev, day, "freight", g, "isolation_cost_day", v, "USD/day", 1.0 if raw else np.nan))
                rows.append((run_id, ev, day, "freight", "unallocated", "isolation_unallocated_flow", unalloc, "trucks/day", np.nan))
                rows.append((run_id, ev, day, "freight", "all", "isolated_flow", raw, "trucks/day", np.nan))
            else:
                for g in GROUPS:
                    rows.append((run_id, ev, day, "freight", g, "isolation_cost_day", 0.0, "USD/day", np.nan))
            # rerouting
            tag = "combined" if case == "combined" else "freight"
            op, bp = d / f"odpfc_{tag}_s1_day{day}.pq", d / f"odpfc_{tag}_s1_day{day}_baseline.pq"
            if op.exists() and bp.exists() and rer_total != 0:
                post, pre = od_cost(op), od_cost(bp)
                j = post.merge(pre, on=KEYS, how="outer", suffixes=("_post", "_pre")).fillna(0.0)
                j["w"] = j.cost_post - j.cost_pre
                jj = attach(j[KEYS + ["w"]], sh)
                if case == "combined":  # mixed passenger+freight file: keep the freight pairs only
                    jj = jj[jj[f"s_{GROUPS[0]}"].notna()]
                vals, unalloc, raw = split(jj, "w", rer_total)
                for g, v in zip(GROUPS, vals):
                    rows.append((run_id, ev, day, "freight", g, "rerouting_cost_day", v, "USD/day", raw / rer_total if rer_total else np.nan))
            else:
                for g in GROUPS:
                    rows.append((run_id, ev, day, "freight", g, "rerouting_cost_day", 0.0, "USD/day", np.nan))
            rows.append((run_id, ev, day, "freight", "all", "rerouting_cost_day_matrix", rer_total, "USD/day", np.nan))
            rows.append((run_id, ev, day, "freight", "all", "isolation_cost_day_matrix", iso_total, "USD/day", np.nan))
            print(run_id, "day", day, "done", flush=True)
    out = pd.DataFrame(rows, columns=["run_id", "event", "day", "class", "sctgG5", "metric", "value", "unit", "recon_ratio"])
    a.out.parent.mkdir(parents=True, exist_ok=True)
    out.to_csv(a.out, index=False)
    print("wrote", a.out, len(out))


if __name__ == "__main__":
    main()
