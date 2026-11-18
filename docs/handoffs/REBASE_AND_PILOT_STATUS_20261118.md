# Rebase and connector pilot — 2026-11-18

Branch: `exp/connector-loading-test1`; worktree `.worktrees/connector-loading-test1`. Rebased onto 701062a. Backup `codex/connector-before-701062a-20261118` retained. No integration merge/push and no network freeze.

## Clark reconciliation

Integration 35f2e8f and experimental 6afc118 were reconciled in the three conflicted files; rebased correction e4ae70e. The shared component calculation remains WEAK, consistent with the solver's undirected physical graph. Both endpoint-array and initialized-link-dataframe interfaces are supported. The latter removes Class-50 connectors and initially unusable links before computing the same physical component. Missing physical classes remain physical.

The valid-end filter runs before allocation, then renormalizes surviving shares. A wholly invalid split or invalid unsplit loading point fails explicitly. CLI `--network-links` and `--road-links` are aliases for the matching initialized physical network. Both regression scenario sets are retained; two old expectations permitting unsafe fallback were deliberately updated to the owner's surviving-exit requirement.

Nine connector-split tests passed locally. The real saved physical network/crosswalk check found a largest weak component of 343,658 nodes: Clark source 55788 maps to **55797 with weight 1.0**. Node 55804 is absent from target allocations. All source weights sum to one within 1e-12; the regression also checks OD conservation at both ends. This is allocation to a physical road node, not changing the ID of a connector link.

## Exemption and pilot

The isolated code/test patch and clean-701062a qualification are in `virtual_exemption_review/README.md`. It remains pending full matched recovery qualification; 3795089 and 3795090 completed successfully, with the two CONUS jobs still running at this status snapshot.

The fixed decision rule, five named counties, assumptions and resource cap are in `AB_CONNECTOR_PILOT_PREREG_20261118.md`. Materiality is at least 5% in either isolation or incremental rerouting cost, separately by county, OD end, six snapshots and freight/combined case. Denominator floors of 100 isolation units/day and $10,000/day produce near-zero absolute guards of 5 units/day and $500/day. Baseline isolation is included; solver residual fails the gate. Origin and destination are never added as unique trips.

Eight analysis jobs at most: preparation; three matched-arm baselines and three recoveries; comparison. Freight A reuses the existing CONUS baseline and qualified recovery. Combined A/B test the same passenger+freight OD and shared physical capacity. Maximum requested envelope is 296 CPU-hours; each primary job has a six-hour cap. Preparation 3796589 was cancelled before compute to correct an input-reader issue; replacement **3796741**, pinned to 55fbecc, waits on the two live CONUS prerequisites. Completed Harvey prerequisites have been checked separately because Slurm no longer accepts their expired live dependency records. Independent clean-patch qualification 3796660 is a separate 65-second test job.

Arm B adds credible exits at existing units only. Geometry and access-time diagnostics will be reviewed before primary assignment submissions. Any county without a credible positive-demand modification fails coverage; no observed impact in an unchanged county cannot justify freezing A. Candidate geometry encodes a local-access cost proxy, not proof of a new physical road. Arm C and demand-weight changes remain deferred.

The canonical integration AGENTS.md has the pilot ledger row; it is intentionally uncommitted there pending owner coordination. The experiment copy was synchronized and committed. Only the experimental remote branch is updated.
