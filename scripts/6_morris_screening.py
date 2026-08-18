"""Script 6 -- Morris screening driver for the Script 1-4 pipeline.

Turns ``parameters/sa_morris_design.json`` (the audited factor table) into a
runnable Morris elementary-effects screening design, and analyzes the results
once the pipeline runs exist. Unlike Script 5's elasticity-based OAT sweep,
this driver produces designs meant to be evaluated by *actually re-running*
the pipeline, one subprocess per run, with per-run parameter overrides
injected through the ``RESIFLOW_PARAM_OVERRIDES`` environment variable (see
``resiflow.parameters`` and ``parameters/README.md``). No file the model reads
by default is ever edited per-run; each run's ``overrides.json`` is the
reproducibility record.

Subcommands
-----------
generate
    Read the design JSON, build a SALib Morris problem (with factor groups),
    sample trajectories, map normalized samples to parameter values
    (log-transform for ``logunif_scale``, index-rounding for ``levels``), and
    emit ``sa_runs/manifest.csv`` plus ``sa_runs/run_####/overrides.json``.
    Each manifest row is tagged with ``min_stage`` -- the earliest pipeline
    stage its changed factor touches (P/1/2/3/4) -- by diffing consecutive
    rows within each trajectory, so the dispatcher can rerun only that stage
    and downstream, reusing cached upstream outputs.

analyze
    Read ``sa_runs/results.csv`` (``run_id`` plus the four output components
    ``direct_damage``, ``rerouting_freight``, ``rerouting_passenger``,
    ``isolation``, collected by the dispatcher from Script 3/4 summary
    outputs), run ``SALib.analyze.morris`` per component, and write
    mu_star / sigma / mu_star_conf CSVs joined with group/tier/stage.
    Components are always reported separately -- never a composite.

--sample
    End-to-end standalone proof: generate a small design, evaluate a synthetic
    analytic model in place of the pipeline, analyze, and print the tornado.
    Runs with no data root, mirroring Script 5's ``--sample`` convention.

Examples
--------
    # Standalone end-to-end sample (no data root required):
    python scripts/6_morris_screening.py --sample

    # Generate the real design (10 optimized trajectories):
    python scripts/6_morris_screening.py generate --trajectories 40 --optimal-trajectories 10

    # Analyze dispatcher-collected results:
    python scripts/6_morris_screening.py analyze

Production preconditions (design JSON `preconditions`): pin assignment
ordering/seeds before trusting sigma, and keep RESIFLOW_MAX_FLOW_ITERATIONS /
RESIFLOW_SAMPLE_OD_N unset (the dispatcher must assert this).
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(1, str(REPO_ROOT))

import numpy as np
import pandas as pd

DEFAULT_DESIGN = REPO_ROOT / "parameters" / "sa_morris_design.json"
DEFAULT_OUT_DIR = REPO_ROOT / "sa_runs"

COMPONENTS: tuple[str, ...] = (
    "direct_damage",
    "rerouting_freight",
    "rerouting_passenger",
    "isolation",
)

#: Pipeline-stage ordering used for min_stage tagging (earliest first).
STAGE_ORDER: dict[str, int] = {"P": 0, "1": 1, "2": 2, "3": 3, "4": 4}

_TRUNCATION_ENV_VARS = ("RESIFLOW_MAX_FLOW_ITERATIONS", "RESIFLOW_SAMPLE_OD_N")


# ---------------------------------------------------------------------------
# Design loading and value mapping
# ---------------------------------------------------------------------------

def load_design(design_path: Path) -> dict:
    with open(design_path, encoding="utf-8") as fh:
        design = json.load(fh)
    factors = design.get("factors", [])
    if not factors:
        raise ValueError(f"No factors found in design file {design_path}")
    for f in factors:
        if f.get("dist") not in {"unif", "logunif_scale", "levels"}:
            raise ValueError(f"Factor {f.get('name')!r}: unknown dist {f.get('dist')!r}")
        if f["dist"] == "levels":
            if not f.get("levels"):
                raise ValueError(f"Factor {f['name']!r}: dist=levels requires 'levels'")
        else:
            lo, hi = f.get("bounds", (None, None))
            if lo is None or hi is None or not lo < hi:
                raise ValueError(f"Factor {f['name']!r}: invalid bounds {f.get('bounds')!r}")
            if f["dist"] == "logunif_scale" and lo <= 0:
                raise ValueError(f"Factor {f['name']!r}: logunif_scale bounds must be > 0")
        if f.get("stage") not in STAGE_ORDER:
            raise ValueError(f"Factor {f['name']!r}: unknown stage {f.get('stage')!r}")
    return design


def build_problem(design: dict) -> dict:
    """SALib problem over the normalized unit hypercube, with factor groups."""
    factors = design["factors"]
    return {
        "num_vars": len(factors),
        "names": [f["name"] for f in factors],
        "groups": [f["group"] for f in factors],
        "bounds": [[0.0, 1.0]] * len(factors),
    }


def map_value(factor: dict, x: float):
    """Map a normalized sample x in [0, 1] to the factor's parameter value."""
    dist = factor["dist"]
    if dist == "levels":
        levels = factor["levels"]
        idx = int(np.rint(float(x) * (len(levels) - 1)))
        return levels[idx]
    lo, hi = (float(b) for b in factor["bounds"])
    if dist == "logunif_scale":
        return float(np.exp(np.log(lo) + float(x) * (np.log(hi) - np.log(lo))))
    return lo + float(x) * (hi - lo)  # unif


def overrides_for_row(design: dict, values: dict[str, object]) -> dict:
    """Build a RESIFLOW_PARAM_OVERRIDES payload from mapped factor values.

    Targets: ``section.key`` sets the value directly (deep-merged over
    unified_parameters.json); ``_scales:path`` multiplies the existing value;
    ``special:handle`` is recorded under ``_dispatch`` for the dispatcher (the
    parameter loader merges it as an inert section).
    """
    overrides: dict = {}
    for factor in design["factors"]:
        value = values[factor["name"]]
        if isinstance(value, np.generic):
            value = value.item()
        target = factor["target"]
        if target.startswith("_scales:"):
            overrides.setdefault("_scales", {})[target[len("_scales:"):]] = value
        elif target.startswith("special:"):
            overrides.setdefault("_dispatch", {})[target[len("special:"):]] = value
        else:
            section, _, key = target.rpartition(".")
            if not section:
                raise ValueError(f"Factor {factor['name']!r}: bad target {target!r}")
            node = overrides
            for part in section.split("."):
                node = node.setdefault(part, {})
            node[key] = value
    return overrides


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------

def _sample_matrix(problem: dict, trajectories: int, num_levels: int,
                   optimal_trajectories: int | None, seed: int) -> np.ndarray:
    from SALib.sample import morris as morris_sample

    kwargs = {"num_levels": num_levels, "seed": seed}
    if optimal_trajectories:
        kwargs["optimal_trajectories"] = optimal_trajectories
    return morris_sample.sample(problem, trajectories, **kwargs)


def generate(design_path: Path, out_dir: Path, *, trajectories: int,
             optimal_trajectories: int | None, num_levels: int, seed: int) -> pd.DataFrame:
    design = load_design(design_path)
    factors = design["factors"]
    names = [f["name"] for f in factors]
    by_name = {f["name"]: f for f in factors}
    problem = build_problem(design)

    set_vars = [v for v in _TRUNCATION_ENV_VARS if os.environ.get(v)]
    if set_vars:
        logging.warning(
            "Truncation env vars set (%s): fine for smoke tests, but the "
            "dispatcher must assert these are UNSET for production SA runs.",
            ", ".join(set_vars),
        )

    X = _sample_matrix(problem, trajectories, num_levels, optimal_trajectories, seed)
    n_groups = len(set(problem["groups"]))
    rows_per_traj = n_groups + 1
    if len(X) % rows_per_traj != 0:
        raise RuntimeError(
            f"Sample rows ({len(X)}) not divisible by groups+1 ({rows_per_traj})"
        )
    n_traj = len(X) // rows_per_traj

    # The earliest stage any factor touches: the first point of each
    # trajectory moves every factor off baseline, so it needs a full rebuild
    # from that stage.
    full_rebuild_stage = min((f["stage"] for f in factors), key=STAGE_ORDER.get)

    records: list[dict] = []
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, xrow in enumerate(X):
        run_id = f"run_{i:04d}"
        traj = i // rows_per_traj
        pos = i % rows_per_traj
        values = {name: map_value(by_name[name], x) for name, x in zip(names, xrow)}

        if pos == 0:
            changed_factor = ""
            changed_group = ""
            min_stage = full_rebuild_stage
        else:
            prev = X[i - 1]
            changed_idx = [j for j in range(len(names)) if xrow[j] != prev[j]]
            if not changed_idx:
                raise RuntimeError(
                    f"Row {i}: no factor changed vs previous row in trajectory {traj}"
                )
            changed_groups = {problem["groups"][j] for j in changed_idx}
            if len(changed_groups) != 1:
                raise RuntimeError(
                    f"Row {i}: multiple groups changed in one Morris step: "
                    f"{sorted(changed_groups)}"
                )
            changed_group = changed_groups.pop()
            changed_factor = ",".join(names[j] for j in changed_idx)
            min_stage = min(
                (by_name[names[j]]["stage"] for j in changed_idx),
                key=STAGE_ORDER.get,
            )

        run_dir = out_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        overrides = overrides_for_row(design, values)
        with open(run_dir / "overrides.json", "w", encoding="utf-8") as fh:
            json.dump(overrides, fh, indent=2)

        rec = {
            "run_id": run_id,
            "trajectory": traj,
            "changed_factor": changed_factor,
            "changed_group": changed_group,
            "min_stage": min_stage,
        }
        rec.update(values)
        records.append(rec)

    manifest = pd.DataFrame.from_records(records)
    manifest.to_csv(out_dir / "manifest.csv", index=False)
    pd.DataFrame(X, columns=names).assign(
        run_id=[f"run_{i:04d}" for i in range(len(X))]
    ).to_csv(out_dir / "sample_normalized.csv", index=False)
    with open(out_dir / "problem.json", "w", encoding="utf-8") as fh:
        json.dump(
            {
                "problem": problem,
                "num_levels": num_levels,
                "design_file": str(design_path),
                "seed": seed,
                "trajectories": n_traj,
            },
            fh,
            indent=2,
        )

    stage_counts = manifest["min_stage"].value_counts().to_dict()
    logging.info(
        "Generated %d runs (%d trajectories x %d rows) -> %s | min_stage counts: %s",
        len(manifest), n_traj, rows_per_traj, out_dir, stage_counts,
    )
    return manifest


# ---------------------------------------------------------------------------
# analyze
# ---------------------------------------------------------------------------

def analyze(design_path: Path, out_dir: Path, results_path: Path | None = None
            ) -> dict[str, pd.DataFrame]:
    from SALib.analyze import morris as morris_analyze

    design = load_design(design_path)
    problem_meta = json.loads((out_dir / "problem.json").read_text(encoding="utf-8"))
    problem = problem_meta["problem"]
    num_levels = int(problem_meta.get("num_levels", 4))

    sample = pd.read_csv(out_dir / "sample_normalized.csv")
    results_path = results_path or (out_dir / "results.csv")
    results = pd.read_csv(results_path)
    if "run_id" not in results.columns:
        raise ValueError(f"{results_path} must have a run_id column")
    missing = [c for c in COMPONENTS if c not in results.columns]
    if missing:
        raise ValueError(f"{results_path} is missing output components: {missing}")

    merged = sample.merge(results, on="run_id", how="left", validate="one_to_one")
    if merged[list(COMPONENTS)].isna().any().any():
        incomplete = merged.loc[
            merged[list(COMPONENTS)].isna().any(axis=1), "run_id"
        ].tolist()
        raise ValueError(
            f"results.csv incomplete: {len(incomplete)} runs missing outputs "
            f"(e.g. {incomplete[:5]}). Morris needs every row of every trajectory."
        )

    X = merged[problem["names"]].to_numpy(dtype=float)

    # group -> tier/stage annotations (a group's stage is the earliest stage
    # of its member factors; tiers are the joined unique member tiers)
    ann: dict[str, dict[str, str]] = {}
    for f in design["factors"]:
        g = ann.setdefault(f["group"], {"tiers": set(), "stages": set()})
        g["tiers"].add(str(f["tier"]))
        g["stages"].add(f["stage"])

    outputs: dict[str, pd.DataFrame] = {}
    for comp in COMPONENTS:
        Y = merged[comp].to_numpy(dtype=float)
        res = morris_analyze.analyze(problem, X, Y, num_levels=num_levels,
                                     print_to_console=False)
        df = pd.DataFrame(
            {
                "group": res["names"],
                "mu_star": res["mu_star"],
                "sigma": res["sigma"],
                "mu_star_conf": res["mu_star_conf"],
                "mu": res["mu"],
            }
        )
        df["tier"] = df["group"].map(lambda g: ",".join(sorted(ann[g]["tiers"])))
        df["stage"] = df["group"].map(
            lambda g: min(ann[g]["stages"], key=STAGE_ORDER.get)
        )
        df = df.sort_values("mu_star", ascending=False).reset_index(drop=True)
        df.to_csv(out_dir / f"morris_{comp}.csv", index=False)
        outputs[comp] = df

    logging.info("Wrote per-component Morris results to %s (morris_<component>.csv)", out_dir)
    return outputs


def print_tornado(outputs: dict[str, pd.DataFrame]) -> None:
    for comp, df in outputs.items():
        print(f"\n=== {comp}: groups ranked by mu* ===")
        show = df.copy()
        for col in ("mu_star", "sigma", "mu_star_conf", "mu"):
            show[col] = show[col].astype(float).round(4)
        print(show[["group", "mu_star", "sigma", "mu_star_conf", "tier", "stage"]]
              .to_string(index=False))


# ---------------------------------------------------------------------------
# --sample: synthetic end-to-end proof
# ---------------------------------------------------------------------------

# Per-component weights over factor *groups* for the synthetic stand-in model.
# Chosen so each component has distinct, plausible heavy hitters; purely
# illustrative -- the point is proving the generate -> evaluate -> analyze
# loop, not the numbers.
_SYNTH_WEIGHTS: dict[str, dict[str, float]] = {
    "direct_damage": {"vulnerability": 3.0, "asset_costs": 2.0, "hazard_thresholds": 1.0},
    "rerouting_freight": {"capacity": 2.5, "demand": 2.0, "econ_time": 1.5,
                          "econ_operating": 1.2, "congestion": 1.0, "speeds": 0.6},
    "rerouting_passenger": {"econ_time": 2.5, "congestion": 1.8, "capacity": 1.5,
                            "speeds": 1.0, "geometry": 0.4},
    "isolation": {"econ_isolation": 3.0, "recovery": 2.0, "hazard_thresholds": 1.5,
                  "geometry": 0.5},
}


def synthetic_outputs(design: dict, sample: pd.DataFrame) -> pd.DataFrame:
    """Deterministic analytic model over the normalized sample matrix."""
    factors = design["factors"]
    groups = {f["name"]: f["group"] for f in factors}
    rows = []
    for _, srow in sample.iterrows():
        rec = {"run_id": srow["run_id"]}
        for comp, weights in _SYNTH_WEIGHTS.items():
            y = 10.0
            for f in factors:
                w = weights.get(groups[f["name"]], 0.0)
                if w:
                    y += w * float(srow[f["name"]])
            # mild interaction so sigma is non-zero for some groups
            if comp == "rerouting_freight":
                y += 1.5 * float(srow.get("capacity_scale", 0.0)) * float(
                    srow.get("freight_demand_scale", 0.0)
                )
            if comp == "direct_damage":
                y += 2.0 * float(srow.get("curve_theta", 0.0)) ** 2
            rec[comp] = y
        rows.append(rec)
    return pd.DataFrame(rows)


def run_sample(design_path: Path, *, seed: int) -> int:
    with tempfile.TemporaryDirectory(prefix="morris_sample_") as tmp:
        out_dir = Path(tmp)
        manifest = generate(
            design_path, out_dir,
            trajectories=6, optimal_trajectories=None, num_levels=4, seed=seed,
        )
        sample = pd.read_csv(out_dir / "sample_normalized.csv")
        design = load_design(design_path)
        results = synthetic_outputs(design, sample)
        results.to_csv(out_dir / "results.csv", index=False)
        outputs = analyze(design_path, out_dir)

        print(f"\nMorris --sample | design={design_path.name} | "
              f"runs={len(manifest)} | synthetic analytic model (no pipeline, no data root)")
        stage_counts = manifest["min_stage"].value_counts().to_dict()
        print(f"min_stage partition of runs: {stage_counts}")
        print_tornado(outputs)
        print("\nOK: generate -> synthetic evaluate -> analyze completed end-to-end.")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--sample", action="store_true",
                        help="End-to-end standalone proof with a synthetic model "
                             "(no data root required).")
    parser.add_argument("--design", default=str(DEFAULT_DESIGN),
                        help="Path to the Morris design JSON.")
    parser.add_argument("--seed", type=int, default=42, help="Sampling seed.")

    sub = parser.add_subparsers(dest="command")

    gen = sub.add_parser("generate", help="Sample the design and emit manifest + overrides.")
    gen.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                     help="Output directory (default: sa_runs/).")
    gen.add_argument("--trajectories", type=int, default=40,
                     help="Trajectories to sample (pool size when optimizing).")
    gen.add_argument("--optimal-trajectories", type=int, default=10,
                     help="Campolongo-optimized subset size (0 disables optimization).")
    gen.add_argument("--levels", type=int, default=4, help="Morris grid levels p.")

    ana = sub.add_parser("analyze", help="Analyze dispatcher-collected results.csv.")
    ana.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR),
                     help="Directory holding manifest/sample/problem (default: sa_runs/).")
    ana.add_argument("--results", default=None,
                     help="results.csv path (default: <out-dir>/results.csv).")

    args = parser.parse_args()
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    design_path = Path(args.design)

    if args.sample:
        return run_sample(design_path, seed=args.seed)

    if args.command == "generate":
        generate(
            design_path, Path(args.out_dir),
            trajectories=args.trajectories,
            optimal_trajectories=args.optimal_trajectories or None,
            num_levels=args.levels,
            seed=args.seed,
        )
        return 0

    if args.command == "analyze":
        outputs = analyze(
            design_path, Path(args.out_dir),
            Path(args.results) if args.results else None,
        )
        print_tornado(outputs)
        return 0

    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
