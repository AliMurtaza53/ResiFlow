# NumCpu regression investigation — 48h plan

**Deliverable:** markdown report for Tom (`notes/perf_findings/REPORT_FOR_TOM.md`).  
**Branch:** `perf/numcpu-regression-diagnosis` (scratch — no production Script 1 edits).

## Goals and status

| Goal | Cap | Status | Artifact |
|------|-----|--------|----------|
| 0 Inventory | 30m | **done** | `notes/perf_findings/GOAL0_SCRIPT1_PARALLEL_INVENTORY.md` |
| 1 Reproduce + instrument | 4h | **in progress** | `experiments/perf_numcpu/runs/` |
| 2 Isolate causes | 8h | pending | per-hypothesis notes in `perf_findings/` |
| 3 Apply fix + benchmark | 6h | pending | |
| 4 SP backend spike | 6h | stretch | |
| 5 Bush PoC | 6h | stretch | |
| 6 Report | 4h | pending | `REPORT_FOR_TOM.md` |

## Guardrails

- Sioux Falls first; CONUS smoke only if time remains.
- No new production dependencies (`psutil` optional in perf venv only).
- Every goal ends with a written finding (even “inconclusive”).

## Quick commands

```powershell
# Goal 1 — Sioux Falls Pass A numcpu sweep (1 iteration)
pip install psutil   # optional, perf venv only
python experiments/perf_numcpu/benchmark_sioux_falls_passa.py --num-cpus 1,2,4,8,16

# Summarize sweep table
python experiments/perf_numcpu/summarize_sweep.py

# Parse a single log
python experiments/perf_numcpu/parse_assignment_timing.py experiments/perf_numcpu/runs/<run>/script1.log --json-out out.json
```

## Prior clone data

See `experiments/perf_numcpu/PRIOR_PASSB_EVIDENCE.md` (summarized from DAFNI-NIRD-clone).
