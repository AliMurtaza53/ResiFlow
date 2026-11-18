# Versioned V1 preparation evidence

This is the small table/decision portion of the stopped pilot, not assignment results. See `../AB_CONNECTOR_PILOT_PREFLIGHT_RESULT_20261118.md` and the unchanged decision rule in `../AB_CONNECTOR_PILOT_PREREG_20261118.md`.

`node_connector_review.csv` lists all 26 tested positive-demand units, logical centroid IDs, graph vertex IDs, associated link/road-end IDs, nominal versus valid counts, and first-failure reasons. Import identifiers as text. C/S are county/sub-county units; G is facility-range; P_alias preserves the existing passenger intake. Nearby facility-reference names are associations, not certified gate identities.

`county_coverage.csv` records 41 additions at 15 units, with zero in Brazoria and Chambers. `rural_rejection_details.csv` distinguishes spacing, bridge/ramp, cut-edge and distance exclusions. `rural_access_route_diagnostic.csv` identifies existing physical routes 491527 (48.2049 m) and 614677;614678 (3,393.7984 m); these are not assigned OD paths. `clark_allocation_check.json` records actual source 55788 → 55797 at 1.0, plus point geometry/CRS. `decision.json` is NEITHER/no freeze/no primary submissions.

The full local bundle, including eight embedded offline maps and the nine-layer GIS package, is at `C:/Users/akothaw/Documents/ChatGPT/Transport Network Analysis/AB_connector_pilot_20261118`. Large GIS/PNG/HTML files remain outside Git. The reproducible exporter is `scripts/diagnostics/export_ab_connector_preflight_review.py`.

The separate exemption review packet has the clean eight-file patch and its code/recovery qualifications. A failed coverage gate is not a failed exemption and is not evidence that A/B assignment impacts are negligible.
