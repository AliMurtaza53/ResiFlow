# CONUS VA toy raster — performance snapshot

**Date:** 2026-07-12  
**Data:** `config.json` → `C:/Users/akothaw/Desktop/data/soge_clusters`  
**Hazard:** `inputs/test_141node_50m/` (VA toy, Track A stand-in)  
**Policy:** NumCpu=1, Patch6 (`NIRD_OD_ID_AT_INSERT=1`, `streaming_arrays`, worker recycle)

---

## Tier 1 — Pass B Script 1 only

**Harness:** `experiments/perf_numcpu/benchmark_conus_passb_numcpu.py`  
**Run:** `experiments/perf_numcpu/runs/conus_snapshot_passb_cpu1_20260712_141307/`

| Metric | Value |
|--------|-------|
| Scope | Full OD (`sample_od_n=0`) |
| Origins | 3,143 |
| Path rows | 9,684,057 |
| Assignment iters | 1 |
| **Wall (s)** | **2,473** |
| LCP pool (s) | 1,057 |
| Streaming pass 1 (s) | 230 |
| Streaming pass 2 (s) | 1,136 |
| od_id assign (s) | 0 |
| baseline.duckdb | 19.5 GB |

**Phase split (wall):** LCP ~43%, stream p2 ~46%, stream p1 ~9%.

---

## Tier 2 — Full pipeline (complete)

**Harness:** `scripts/run_conus_smoke_50k.ps1`  
**Args:** `-SampleOdN 0 -MaxFlowIterations 1 -NumCpu 1 -ResultsVariant conus_snapshot_full -EventKeys 1`  
**Results:** `C:/Users/akothaw/Desktop/data/results` variant `conus_snapshot_full`  
**Logs:** `logs/20260712_145448_passA_script1.log` through `logs/20260712_161740_script4_event1.log`

| Step | Wall (s) | Notes |
|------|----------|-------|
| Pass A (Script 1) | ~1,709 | LCP 1,055 s, stream p2 378 s |
| Script 2 (event 1) | ~553 | hazard ∩ links |
| Export damaged edges | ~3 | trivial |
| Script 3 (+ postprocess) | ~279 | direct damage |
| Pass B (Script 1) | ~2,421 | LCP 1,050 s, stream p2 1,110 s |
| Script 4 (event 1) | ~3,347 | ~20 assignment solves (recovery × modes) |
| **End-to-end** | **~8,332 (~2 h 19 min)** | |

**Note:** 1 assignment iteration → Pass A/B stop at ~52% remain (not converged); timings are valid for perf profiling, not equilibrium quality.

---

## Verdict

| Finding | Implication |
|---------|-------------|
| Pass B Script 1 ~40 min | LCP + streaming p2 dominate Script 1 |
| **Script 4 ~56 min** | **Largest single stage** at full OD — repeated subgraph assignment |
| Script 2 + export + Script 3 ~14 min | Not on critical path for VA toy window |
| NumCpu=1 | Keep for CONUS (NumCpu=2 regresses ~55%) |

---

## Implementation reference

- Pipeline: [`docs/PIPELINE_OVERVIEW.md`](../../docs/PIPELINE_OVERVIEW.md)
- Script 1 parallel path: [`GOAL0_SCRIPT1_PARALLEL_INVENTORY.md`](GOAL0_SCRIPT1_PARALLEL_INVENTORY.md)
- Prior numcpu work: [`CHECKPOINT.md`](CHECKPOINT.md), [`REPORT_FOR_TOM.md`](REPORT_FOR_TOM.md)

---

## Planning next steps

| Priority | Action |
|----------|--------|
| 1 | Profile / optimize **Script 4** rerouting loop (biggest wall share) |
| 2 | Optimize Script 1 **streaming pass 2** (path realization) |
| 3 | Keep NumCpu=1 for CONUS |
| 4 | Script 2 / export — defer |
