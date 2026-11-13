#!/bin/bash
# Login-node submitter: baseline, then stages 2-4 once the baseline exits 0. Run from the repo root after git pull --ff-only.
set -e
D=experiments/pass_a_convergence/hopper
J1=$(sbatch --parsable $D/submit_harvey_conus_baseline.slurm)
J2=$(sbatch --parsable --dependency=afterok:$J1 $D/submit_harvey_conus_stages2to4.slurm)
echo "baseline $J1 -> stages2to4 $J2"
