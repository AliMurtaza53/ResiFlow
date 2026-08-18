"""Tests for the Script 6 Morris screening driver (generate/analyze/--sample)."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = REPO_ROOT / "parameters" / "sa_morris_design.json"

# The script filename starts with a digit, so import it by path.
_spec = importlib.util.spec_from_file_location(
    "morris_screening", REPO_ROOT / "scripts" / "6_morris_screening.py"
)
m6 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(m6)


@pytest.fixture(scope="module")
def design() -> dict:
    return m6.load_design(DESIGN_PATH)


@pytest.fixture(scope="module")
def generated(tmp_path_factory, design):
    out_dir = tmp_path_factory.mktemp("sa_runs")
    manifest = m6.generate(
        DESIGN_PATH, out_dir,
        trajectories=4, optimal_trajectories=None, num_levels=4, seed=7,
    )
    return out_dir, manifest


# ---------------------------------------------------------------------------
# design + value mapping
# ---------------------------------------------------------------------------

def test_design_loads_and_matches_handoff_shape(design):
    names = {f["name"] for f in design["factors"]}
    # spot-check factors from every stage of the Section 6 table
    for expected in (
        "vot_scale", "capacity_scale", "flood_closure_threshold_cm",
        "curve_theta", "recovery_gate_scale", "faf5_default_lanes",
    ):
        assert expected in names
    excluded = {e["name"] for e in design.get("excluded", [])}
    assert "fuel_curve_scale" in excluded


def test_map_value_unif_logunif_levels():
    unif = {"dist": "unif", "bounds": [10.0, 24.0]}
    assert m6.map_value(unif, 0.0) == 10.0
    assert m6.map_value(unif, 1.0) == 24.0
    assert m6.map_value(unif, 0.5) == pytest.approx(17.0)

    log = {"dist": "logunif_scale", "bounds": [0.5, 2.0]}
    assert m6.map_value(log, 0.0) == pytest.approx(0.5)
    assert m6.map_value(log, 1.0) == pytest.approx(2.0)
    assert m6.map_value(log, 0.5) == pytest.approx(1.0)  # geometric midpoint

    lev = {"dist": "levels", "levels": [15, 30, 60]}
    assert m6.map_value(lev, 0.0) == 15
    assert m6.map_value(lev, 1.0) == 60
    assert m6.map_value(lev, 0.5) == 30


def test_overrides_for_row_routes_targets(design):
    values = {}
    for f in design["factors"]:
        values[f["name"]] = m6.map_value(f, 0.5)
    ov = m6.overrides_for_row(design, values)
    # plain dotted path -> nested section/key
    assert ov["assignment"]["capacity_scale"] == pytest.approx(0.85)
    assert "curve_theta" in ov["vulnerability"]
    # _scales: targets land in the reserved section
    assert "cost_time.vot_usd_per_hour" in ov["_scales"]
    assert "recovery.residual_depth_gates_m" in ov["_scales"]
    # special: targets land under _dispatch (inert to the loader)
    assert "recovery_pathway" in ov["_dispatch"]
    # everything JSON-serializable (no numpy scalars)
    json.dumps(ov)


def test_scales_paths_in_design_exist_in_unified_parameters(design, monkeypatch, tmp_path):
    """Every _scales target must resolve after the merge, or generate would
    emit overrides that make the pipeline fail loud at load time."""
    from resiflow.parameters import clear_cache, load_unified_parameters

    values = {f["name"]: m6.map_value(f, 0.5) for f in design["factors"]}
    ov_payload = m6.overrides_for_row(design, values)
    ov_path = tmp_path / "overrides.json"
    ov_path.write_text(json.dumps(ov_payload), encoding="utf-8")
    monkeypatch.setenv("RESIFLOW_PARAM_OVERRIDES", str(ov_path))
    clear_cache()
    try:
        data = load_unified_parameters(params_root=REPO_ROOT / "parameters")
    finally:
        monkeypatch.delenv("RESIFLOW_PARAM_OVERRIDES")
        clear_cache()
    # spot-check a scale actually multiplied the dict coherently
    gates = data["recovery"]["residual_depth_gates_m"]
    ratio = gates["deep"] / gates["intermediate"]
    assert ratio == pytest.approx(3.0)  # 6/2 preserved by a coherent scale


# ---------------------------------------------------------------------------
# generate
# ---------------------------------------------------------------------------

def test_generate_emits_manifest_and_overrides(generated, design):
    out_dir, manifest = generated
    n_groups = len({f["group"] for f in design["factors"]})
    assert len(manifest) == 4 * (n_groups + 1)
    assert (out_dir / "manifest.csv").exists()
    assert (out_dir / "sample_normalized.csv").exists()
    assert (out_dir / "problem.json").exists()
    for run_id in manifest["run_id"]:
        assert (out_dir / run_id / "overrides.json").exists()


def test_generate_stage_tags_partition_correctly(generated, design):
    out_dir, manifest = generated
    stage_of_group = {}
    for f in design["factors"]:
        g = stage_of_group.setdefault(f["group"], set())
        g.add(f["stage"])
    # first row of each trajectory: full rebuild from the earliest stage
    firsts = manifest[manifest["changed_group"] == ""]
    assert (firsts["min_stage"] == "P").all()
    assert len(firsts) == manifest["trajectory"].nunique()
    # spot-checks from the definition of done: a vulnerability (theta) step is
    # stage 3; a capacity step is stage 1
    vuln = manifest[manifest["changed_group"] == "vulnerability"]
    assert not vuln.empty and (vuln["min_stage"] == "3").all()
    cap = manifest[manifest["changed_group"] == "capacity"]
    assert not cap.empty and (cap["min_stage"] == "1").all()
    # every step's tag equals the earliest stage of its changed group
    steps = manifest[manifest["changed_group"] != ""]
    for _, row in steps.iterrows():
        expected = min(stage_of_group[row["changed_group"]], key=m6.STAGE_ORDER.get)
        assert row["min_stage"] == expected


def test_generate_values_respect_bounds(generated, design):
    _, manifest = generated
    for f in design["factors"]:
        vals = pd.to_numeric(manifest[f["name"]])
        if f["dist"] == "levels":
            assert set(vals.unique()) <= set(f["levels"])
        else:
            lo, hi = f["bounds"]
            assert vals.min() >= lo - 1e-9
            assert vals.max() <= hi + 1e-9


# ---------------------------------------------------------------------------
# analyze (synthetic end-to-end, mirrors --sample)
# ---------------------------------------------------------------------------

def test_analyze_ranks_synthetic_heavy_hitters(generated, design):
    out_dir, manifest = generated
    sample = pd.read_csv(out_dir / "sample_normalized.csv")
    results = m6.synthetic_outputs(design, sample)
    results.to_csv(out_dir / "results.csv", index=False)

    outputs = m6.analyze(DESIGN_PATH, out_dir)
    assert set(outputs) == set(m6.COMPONENTS)
    dd = outputs["direct_damage"]
    # synthetic model weights vulnerability heaviest for direct damage
    assert dd.iloc[0]["group"] == "vulnerability"
    assert dd.iloc[0]["mu_star"] > 0
    assert {"group", "mu_star", "sigma", "mu_star_conf", "tier", "stage"} <= set(dd.columns)
    for comp in m6.COMPONENTS:
        assert (out_dir / f"morris_{comp}.csv").exists()


def test_analyze_fails_loud_on_incomplete_results(generated, design, tmp_path):
    out_dir, manifest = generated
    sample = pd.read_csv(out_dir / "sample_normalized.csv")
    results = m6.synthetic_outputs(design, sample).iloc[:-3]  # drop rows
    partial = tmp_path / "partial_results.csv"
    results.to_csv(partial, index=False)
    with pytest.raises(ValueError, match="incomplete"):
        m6.analyze(DESIGN_PATH, out_dir, partial)
