# Virtual centroid connector flood exemption

Implemented on exp/connector-loading-test1 on 2026-11-18. Loading locations, OD quantities, physical capacities and the routing solver are unchanged.

Native FAF Class 50 and explicitly tagged generated centroid connectors are recognized by a shared null-safe helper. Missing physical road classes remain eligible for hazard exposure. These links are removed before raster intersection, retained in the routing graph, and receive an explicit hazard_exposure_applicable=false flag. Legacy flood depth/intensity fields use zero as a non-applicable sentinel, not an observed depth. Both passenger and truck speed caps retain baseline free-flow values.

Stage-2 aggregation and flood damage pricing reject virtual-link intersection records. Recovery rejects legacy connector depth, damage or speed restrictions before selecting disrupted OD, and checks again after the damage overlay. Existing contaminated outputs must be regenerated; the guard does not silently repair them. Physical access roads remain subject to normal hazards and recovery.

Hopper isolated snapshot: /scratch/akothaw/multimodal_hazard_data/code/ResiFlow_virtual_exemption_20261118. No shared runtime checkout was modified.

Regression job 3795034: 24 passed, two expected/environment warnings, 58.36 seconds. Includes new classification/raster exclusion/physical-state/stale-artifact tests; wet virtual lines with dry physical access; one/two physical exits; adjacent-road non-access; no third-centroid shortcuts; existing Anaheim routing and Sioux Falls flood pipeline. Initial local collection lacked snail, so tests used Hopper's existing nird environment and isolated pytest_pkgs. Initial Hopper job 3795025 lacked pytest on PYTHONPATH and performed no tests; the corrected job above passed.

The matched recovery reruns will reuse all four existing baselines, use fresh output variants, and profile stages 2–4. A new verifier must pass after stage 2: identical physical link IDs, capacities, depths, damage classes and speed caps; zero virtual exposure; all 3,795 virtual routing links retained and unrestricted. After stage 3, direct physical damage must match the old arm within 1e-9 relative tolerance. Recovery path exports must retain zero centroid shortcuts at all six snapshots. Previous outputs remain available and are still marked provisional.

The separate multi-connector proposal is in MULTICONNECTOR_DESIGN_PLAN.md. It has not been implemented or mixed into this correction.
