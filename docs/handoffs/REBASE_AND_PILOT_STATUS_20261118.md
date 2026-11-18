# Rebase, exemption and pilot status — 2026-11-18

Branch: `exp/connector-loading-test1`, rebased onto **701062a**. No integration push/merge, branch deletion or network freeze. Backup `codex/connector-before-701062a-20261118` retained.

## Clark resolution

Integration **35f2e8f** and experimental **6afc118** were deliberately reconciled in `connector_split.py`, `prepare_passenger_od_variants.py` and `test_connector_split.py` (rebased correction e4ae70e). The shared calculation is the largest WEAK physical component, not an SCC filter. Both endpoint-array and initialized-dataframe APIs remain; `--network-links` and `--road-links` are aliases. Invalid exits are dropped before allocation and surviving shares renormalized. All-invalid/invalid-unsplit points fail rather than silently falling back.

Both regression scenario sets remain. Two old unsafe fallback expectations were updated to the owner's surviving-exit requirement. Nine split tests passed. Actual saved network/crosswalk verification found a 343,658-node main weak component; source **55788 maps to 55797 at 1.0** and 55804 receives zero. All source weights sum to one within 1e-12. The downloaded actual node_targets row and GIS check reproduce that result.

## Exemption

All four recovery jobs **3795089–3795092 passed**: unchanged physical hazard state and $1,468,883,828.539848 damage; 3,795 unrestricted virtual links with zero exposure; 48 conserved recovery solves and 48 zero-shortcut path exports. The review packet is in `virtual_exemption_review/README.md`.

Final scope review identified the separate earthquake/landslide/winter sampler. The same exclusion, applicability flag and stale-input guard have now been extended there. Its independent clean-701062a qualification is recorded in the review packet; the validated flood calculation is unchanged. No exemption merge has been performed.

## Pilot STOP

Preparation **3797277** passed 44 regressions and generated 41 added exits at 15 of 26 units, then stopped at the registered five-county coverage gate: LA 21 new exits, Harris 14, Clark 6, Brazoria 0, Chambers 0. No primary assignments were submitted. **Neither A nor B is selected or frozen.** No convergence/isolation/FAF-agreement conclusion follows.

Brazoria's paired carriageway ends are 48.2 m apart, excluded by the 150 m spacing rule; Chambers' eligible 3.394 km route exceeds the 3.0 km cap. The exact node/link evidence and facility cut-edge exceptions are in `AB_CONNECTOR_PILOT_PREFLIGHT_RESULT_20261118.md`. Geometry rules were not relaxed after failure.

The materiality rule remains **5%**, using floors of 100 isolation units/day and $10,000/day (near-zero guards: 5 trucks/PCE per day and $500/day). Baseline isolation is included, and matched cost cohorts are checked per OD pair. The rule has not been applied because primary assignments have not run.

Review: `C:/Users/akothaw/Documents/ChatGPT/Transport Network Analysis/AB_connector_pilot_20261118/index.html` (eight embedded offline maps), `preflight_findings.gpkg`, and `node_connector_review.csv`. The proposed, unexecuted next geometry sensitivity is in `AB_CONNECTOR_PILOT_GEOMETRY_V2_PROPOSAL_20261118.md`.

Pilot preparation used 2:49 wall time, 0.188 allocated CPU-hours, 113.707 actual CPU-seconds and about 4.79 GiB peak RSS. Three setup revisions were cancelled before compute. No primary baseline/recovery resources were spent. The canonical AGENTS.md ledger draft remains uncommitted on integration; only the synchronized experiment copy is committed.
