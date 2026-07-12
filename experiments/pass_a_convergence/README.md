# Pass A convergence diagnostics

Scratch experiments for the Pass A stall investigation. **Not production code.**

## Parse clone log

```powershell
python experiments/pass_a_convergence/parse_assignment_log.py `
  C:\Users\akothaw\Desktop\DAFNI-NIRD-clone\logs\20260629_075855_passA_script1_baseline.log `
  --json-out experiments/pass_a_convergence/runs/clone_parsed.json `
  --csv-out experiments/pass_a_convergence/runs/clone_iterations.csv
```

## Sioux Falls convergence run

```powershell
python experiments/pass_a_convergence/run_sioux_convergence.py --mode baseline
python experiments/pass_a_convergence/run_sioux_convergence.py --mode fractional
```

## Hazard resolution / footprint (Goal 5)

```powershell
python experiments/pass_a_convergence/hazard_footprint_sweep.py
```

Findings: `notes/perf_findings/GOAL1_STALL_CHARACTERIZATION.md`, … `GOAL5_HAZARD_RESOLUTION_FOOTPRINT.md`; report: `notes/perf_findings/REPORT_PASS_A_CONVERGENCE.md`
