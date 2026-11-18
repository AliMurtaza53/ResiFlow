# Connector pilot: STOP at the preregistered coverage gate

The rebase and exemption qualification are complete. The A/B assignment comparison is **not complete**: preparation stopped before any primary assignment submission. Neither network is selected or frozen. Do not interpret the unchanged rural cases as a non-material assignment effect.

## Completed prerequisites

Branch `exp/connector-loading-test1` is rebased onto 701062a. Integration 35f2e8f's largest WEAK component guard and experimental 6afc118's invalid-end rejection/renormalization were reconciled in the three Clark files; both scenario sets are retained. Nine split tests passed. Two unsafe old fallback expectations were deliberately updated rather than silently choosing a conflict side. Actual corrected allocation: source 55788 → **55797 at weight 1.0**, with zero to 55804 and total demand conserved.

All four matched recovery jobs 3795089–3795092 exited 0. Physical hazard states and $1,468,883,828.539848 damage were unchanged; all 3,795 virtual links remained unrestricted with zero exposure. All 48 recovery solves passed conservation/residual checks, and all 48 path exports had zero shortcuts. The code/test-only exemption patch is **ready for owner review** in `virtual_exemption_review/`; its final all-hazard clean-701062a qualification validated 60 unique executed checks (59 broad successes plus the corrected winter case; two real-data tests skipped). The focused final run 3798972 passed all 15 exemption checks. No integration merge/push occurred.

## Preparation result

Job **3797277**, immutable source **df4bcb0**, passed **44 regression tests** before constructing the candidates. It then exited 1 at the explicit county-coverage assertion, not at a solver or data-reader failure.

- Los Angeles / Long Beach: 8 of 11 positive units modified; 21 added exits.
- Harris: 5 of 7 modified; 14 added exits.
- Clark WA: 2 of 3 modified; 6 added exits.
- Brazoria: 0 of 3 modified; zero added exits.
- Chambers: 0 of 2 modified; zero added exits.

Total: **41 added exits at 15 of 26 units**. Twelve units reach four valid exits, two reach three, two have two, and ten remain at one. Nominal and valid counts are kept separate, including Clark's retained inactive 55804 record. Original native C/S/G connectors remain; passenger aliases exist identically in both arms with a conservative nonbinding computational capacity. No physical roads or demand quantities changed.

Inputs remain 1,510,749.556669 trucks/day and 51,718,653.8941 passenger trips/day; the combined solver uses 54,740,153.0074384 PCE/day. Both source matrices contain zero same-node flow. Only the five named counties receive proposed additional access; the intended assignments retain full-CONUS demand/background traffic.

## Why the rural cases failed

**Brazoria:** county logical centroid 48039 is graph node 393038, loading at road node 88897. Alternative 88898 is only **48.2049 m** away and is connected by ordinary physical link **491527, CR 46**. It was rejected by the **150 m spacing rule**, not by disconnection. The passenger intake starts at 88898 and encounters the reciprocal exclusion. Nearby node 88896 has only bridge/ramp attachments. These paired carriageway ends are a potential *directional loading* sensitivity, not automatically two independent geographic gates.

The Freeport-associated G unit (logical 100115, graph 445114) loads at 88916 through single modeled access edge **491549**, an ordinary road joining 88912. Other candidates would bypass that cut edge. A connected terminal spur is not the Clark disconnected-island defect, and it should not be “fixed” by deleting the real access-road dependency. The real complex may have other gates; current screening does not establish them.

**Chambers:** county logical centroid 48071 is graph node 393070, loading at 111060. Eligible alternative **111057** has a structure-free physical route of **3,393.7984 m** on **614677;614678**. It fails the fixed **3,000 m** routed-access cap by 393.8 m. Nearby 111062 has only bridge/ramp attachments. This is a distance-window exclusion, not evidence of a convergence defect.

The first-failure audit is not an exhaustive real-world access survey. In particular, no inference that Brazoria or Chambers truly has only one usable county access follows from this restricted existing-node screen.

## Decision and remaining question

The preregistered materiality rule remains unchanged: at least 5% in county isolation or incremental rerouting cost, with denominator floors of 100 units/day and $10,000/day (near-zero guards of 5 trucks/PCE per day and $500/day). Baseline failures count in isolation; costs compare the same routed OD quantities within each arm. Origin and destination views remain separate.

Those measures, convergence, loading saturation and new FAF22 agreement **have not been computed for A/B**. Coverage failed before the time-only range diagnostic and before the six primary jobs. Their scripts are staged, not submitted. Decision: **NEITHER; no freeze**.

The proposed next protocol is in `AB_CONNECTOR_PILOT_GEOMETRY_V2_PROPOSAL_20261118.md`. It is a proposal, not an implemented or authorized rerun, and does not retroactively change V1's failure.

## Review files and cost

Local review folder: `C:/Users/akothaw/Documents/ChatGPT/Transport Network Analysis/AB_connector_pilot_20261118`. `index.html` embeds eight offline maps; `preflight_findings.gpkg` supports GIS review; `node_connector_review.csv` lists all 26 units, graph/logical IDs, every connector and exception reasons. Small result tables are versioned in `ab_connector_pilot_review_20261118/`. The physical-route diagnostic layer is not an assigned OD-path export.

Preparation elapsed **2:49**, allocated **676 CPU-seconds (0.188 CPU-hours)**, actual CPU **113.707 seconds**, peak RSS about **4.79 GiB**. Its successful regression stage is in stages.tsv; the wrapper exited at the failed preparation stage before appending that stage's TSV row, so full-job resource figures come from Slurm. Three earlier queued setup revisions were cancelled before compute: zero allocated CPUs/time. No primary baseline/recovery CPU was spent. The 296 CPU-hour scientific allocation cap has not been extended.

Canonical AGENTS.md is updated as an uncommitted integration ledger draft; the synchronized experiment copy and this report are committed only on the experimental branch. No branch was deleted.
