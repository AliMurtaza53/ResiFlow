# Virtual centroid connector flood exemption

Implemented on exp/connector-loading-test1 on 2026-11-18. Loading locations, OD quantities, physical capacities and the routing solver are unchanged.

Native FAF Class 50 and explicitly tagged generated centroid connectors are recognized by a shared null-safe helper. Missing physical road classes remain eligible for hazard exposure. These links are removed before raster intersection, retained in the routing graph, and receive an explicit hazard_exposure_applicable=false flag. Legacy flood depth/intensity fields use zero as a non-applicable sentinel, not an observed depth. Both passenger and truck speed caps retain baseline free-flow values.

Stage-2 aggregation and flood damage pricing reject virtual-link intersection records. Recovery rejects legacy connector depth, damage or speed restrictions before selecting disrupted OD, and checks again after the damage overlay. Existing contaminated outputs must be regenerated; the guard does not silently repair them. Physical access roads remain subject to normal hazards and recovery.

Hopper isolated snapshot: /scratch/akothaw/multimodal_hazard_data/code/ResiFlow_virtual_exemption_20261118. No shared runtime checkout was modified.

Regression job 3795034: 24 passed, two expected/environment warnings, 58.36 seconds. Includes new classification/raster exclusion/physical-state/stale-artifact tests; wet virtual lines with dry physical access; one/two physical exits; adjacent-road non-access; no third-centroid shortcuts; existing Anaheim routing and Sioux Falls flood pipeline. Initial local collection lacked snail, so tests used Hopper's existing nird environment and isolated pytest_pkgs. Initial Hopper job 3795025 lacked pytest on PYTHONPATH and performed no tests; the corrected job above passed.

The matched recovery reruns will reuse all four existing baselines, use fresh output variants, and profile stages 2–4. A new verifier must pass after stage 2: identical physical link IDs, capacities, depths, damage classes and speed caps; zero virtual exposure; all 3,795 virtual routing links retained and unrestricted. After stage 3, direct physical damage must match the old arm within 1e-9 relative tolerance. Recovery path exports must retain zero centroid shortcuts at all six snapshots. Previous outputs remain available and are still marked provisional.

The separate multi-connector proposal is in MULTICONNECTOR_DESIGN_PLAN.md. It has not been implemented or mixed into this correction.

## Submitted matched recovery runs

Code revision 4409abf; operation manifest `/scratch/akothaw/multimodal_hazard_data/stage2_scripts/virtual_exemption_reruns_20261118/manifest.json`.

- Harvey-15 C+S control: 3795089.
- Harvey-15 C+S+G: 3795090.
- CONUS C+S control: 3795091.
- CONUS C+S+G: 3795092.

Initial launches 3795084–3795087 stopped before stage 2 because the archived profiling shell helper contained CRLF line endings. Only that helper in the isolated snapshot was normalized to LF; the failed attempts created no analysis outputs or baseline aliases. The replacement jobs above were confirmed RUNNING in stage 2.

Fresh output variants append `_virtual_exempt` to each original arm. No baseline assignment or edge-index rebuild is submitted; the existing baseline artifacts are reused. Each job includes physical-state verification after stage 2, physical-damage verification after stage 3, stage profiling and recovery shortcut audits. Same original eight CPUs, 600 GB allocation and 15-iteration recovery cap. Controls and gateway arms use their original OD files.

The source snapshot is the tested precommit source corresponding to 4409abf, with the new verification script staged subsequently and a SOURCE_REVISION.txt marker. Relative to the old recorded 19b02b1 runtime, inherited non-flood winter-storm/earthquake updates and the passenger-only split builder are inactive in this flood experiment; the physical-state/damage verifiers enforce the intended single-factor difference.
