# %%
"""Reconstruct Script 4's final cost_matrix_*_by_scenario.csv from whatever
per-day artifacts already exist on disk.

Script 4 (4_rerouting_and_recovery_scenario_loop.py) writes each recovery
day's results to its own uniquely-named file as it completes
(rerouting_cost_{mode}_s{scenario}_day{day}.csv,
trip_isolations_{mode}_s{scenario}_day{day}.csv) but only writes the final
rolled-up cost_matrix_{mode}_by_scenario.csv AFTER the entire day loop
finishes. If the job is killed partway (e.g. a SLURM time-limit kill), the
per-day files for every day that did complete are safe on disk, but the
final rollup never gets written -- there was no way to get it without
finishing the whole run.

This script rebuilds that rollup from whatever per-day files exist, with no
risk to a still-running job (it only reads files, never writes into the
job's own output tree except the final cost_matrix csv, and only appends
new day rows -- it never touches or deletes an existing per-day file).

Usage:
    python scripts/recover_partial_rerouting_results.py <depth_key> <flood_key>

Example (matches Script 4's own CLI convention):
    python scripts/recover_partial_rerouting_results.py 602 1
"""
import re
import sys
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from resiflow.utils import get_results_variant, load_config  # noqa: E402

DAY_FILE_RE = re.compile(r"^rerouting_cost_(?P<mode>.+)_s(?P<scenario>-?\d+)_day(?P<day>-?\d+)\.csv$")


def load_completed_day_cost_row(out_path: Path, out_mode: str, scenario_id, event_day) -> dict | None:
    """Reconstruct one day's final-aggregate cost row from its per-day artifacts.

    Two fields (isolation_flow, isolation_cost_usd) are only ever added to
    the IN-MEMORY row after the per-day rerouting_cost CSV is written (see
    Script 4's day loop), so they're absent from that CSV -- recompute them
    here from the matching trip_isolations CSV (sum(Car21) /
    sum(isolation_cost_usd)) so a reconstructed row matches what an
    uninterrupted run would have produced.
    """
    cost_csv = out_path / f"rerouting_cost_{out_mode}_s{scenario_id}_day{event_day}.csv"
    iso_csv = out_path / f"trip_isolations_{out_mode}_s{scenario_id}_day{event_day}.csv"
    if not cost_csv.exists() or not iso_csv.exists():
        return None
    cost_df = pd.read_csv(cost_csv)
    if cost_df.empty:
        return None
    row = cost_df.iloc[-1].to_dict()
    iso_df = pd.read_csv(iso_csv)
    row["isolation_flow"] = float(
        pd.to_numeric(iso_df.get("Car21", pd.Series(dtype=float)), errors="coerce").fillna(0.0).sum()
    )
    row["isolation_cost_usd"] = float(
        pd.to_numeric(iso_df.get("isolation_cost_usd", pd.Series(dtype=float)), errors="coerce")
        .fillna(0.0)
        .sum()
    )
    return row


def discover_completed_days(out_path: Path) -> dict[str, list[tuple[int, int]]]:
    """Scan out_path for per-day cost files; return {out_mode: [(scenario, day), ...]}."""
    found: dict[str, list[tuple[int, int]]] = {}
    for f in out_path.glob("rerouting_cost_*_s*_day*.csv"):
        m = DAY_FILE_RE.match(f.name)
        if not m:
            continue
        mode = m.group("mode")
        found.setdefault(mode, []).append((int(m.group("scenario")), int(m.group("day"))))
    for mode in found:
        found[mode] = sorted(set(found[mode]), key=lambda t: t[1])
    return found


def main(depth_key: int, flood_key: int) -> int:
    base_path = Path(load_config()["paths"]["soge_clusters"])
    results_variant = get_results_variant()
    out_path = (
        base_path.parent
        / "results"
        / "rerouting_analysis"
        / results_variant
        / str(depth_key)
        / str(flood_key)
    )
    if not out_path.exists():
        print(f"No rerouting output directory found at {out_path}")
        return 1

    # Expected full day list, for an honest completeness report.
    try:
        sys.path.insert(0, str(REPO_ROOT / "scripts"))
        import importlib.util

        spec = importlib.util.spec_from_file_location(
            "script4", REPO_ROOT / "scripts" / "4_rerouting_and_recovery_scenario_loop.py"
        )
        script4 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(script4)
        _, _, scenarios, conditions = script4.load_scenarios(base_path)
        expected_days = list(zip(scenarios, conditions))
    except Exception as exc:  # pragma: no cover - best-effort completeness check only
        print(f"(Could not load expected day list for a completeness check: {exc})")
        expected_days = None

    completed = discover_completed_days(out_path)
    if not completed:
        print(f"No completed per-day files found under {out_path}")
        return 1

    for out_mode, day_pairs in completed.items():
        rows = []
        for scenario_id, event_day in day_pairs:
            row = load_completed_day_cost_row(out_path, out_mode, scenario_id, event_day)
            if row is not None:
                rows.append(row)
        if not rows:
            continue
        cost_df = pd.DataFrame(rows).sort_values("event_day").reset_index(drop=True)
        cost_df["combined_total_cost"] = (
            cost_df["rerouting_cost"] + cost_df["isolation_cost"] + cost_df["direct_damage_total"]
        )
        out_file = out_path / f"cost_matrix_{out_mode}_by_scenario.RECOVERED.csv"
        cost_df.to_csv(out_file, index=False)
        print(f"mode={out_mode}: recovered {len(cost_df)} of "
              f"{len(expected_days) if expected_days else '?'} days -> {out_file}")
        if expected_days is not None and len(cost_df) < len(expected_days):
            missing = sorted(set(expected_days) - set(day_pairs))
            print(f"  missing (scenario, day) pairs: {missing}")
        if out_mode == "freight":
            legacy_file = out_path / "cost_matrix_by_scenario.RECOVERED.csv"
            cost_df.to_csv(legacy_file, index=False)
            print(f"  also wrote legacy alias -> {legacy_file}")

    return 0


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python scripts/recover_partial_rerouting_results.py <depth_key> <flood_key>")
        sys.exit(1)
    sys.exit(main(int(sys.argv[1]), int(sys.argv[2])))
