# Harvey-15 stages 2–4 rerun on Hopper

## Goal

Rerun flood intersection, sourced direct damage, postprocessing, and freight rerouting and recovery for Harvey-15.

## Method

Submitted the unedited `submit_harvey15_stages2to4_v2.slurm` from the Hopper login node after a clean fast-forward check at `ddadbe3`. I interpreted the owner's explicit instruction to submit as sign-off on the masked raster. Retirement test job `3699865` recorded 39 passes and 12 warnings.

## Prior knowledge

The existing 15-iteration freight baseline and edge-to-OD index were present and reused. The intended inputs were the masked metre-based Harvey raster and sourced asset costs. The submission log reached the archive step and confirmed the baseline. Commit `7a78942`, published after submission, fixes an issue where damage postprocessing could overwrite sourced costs with zeros.

## Outcome

Slurm job `3699951` failed on `amd069` after 3 seconds with exit code `127:0`. The batch step reached the Stage 2 heading. The profiling wrapper failed before it launched the intersection script.

First stderr line, verbatim:

```text
/var/spool/slurmd/job3699951/slurm_script: line 16: module: command not found
```

Fatal error, verbatim:

```text
/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_harvey/experiments/common/profile_stage.sh: line 39: /usr/bin/time: No such file or directory
```

| Requested check | Result |
|---|---|
| Direct damage by asset type and damaged-link counts | Unavailable. Stage 3 did not run. |
| Major-road and bridge breakdown, closures, depth distribution | Unavailable. Stage 2 did not run. The code aggregates each link's piece depths by maximum. |
| Geodesic-to-projected ratio and p01, p50, p99 | Unavailable. Stage 2 produced no new length check. |
| Wall time, peak RSS, CPU efficiency by stage | Unavailable. Slurm recorded 3 seconds elapsed and `89508K` batch MaxRSS. |
| Day-0 costs, 90-day recovery, largest rerouted OD pairs | Unavailable. Stage 4 did not run. |

Logs are `/home/akothaw/multimodal_hazard_project/logs_harvey15_stages2to4_v2_3699951.{out,err}`. The handoff calls for stopping on failure and referring the profiling dependency to Claude. The job script and shared code were left as submitted.
