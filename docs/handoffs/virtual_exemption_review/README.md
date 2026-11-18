# Virtual-link hazard exemption: isolated review change set

Status: code/test qualification passed; matched recovery qualification PENDING until all four jobs below pass. This is not merged or approved for the envelope.

`virtual_exemption.patch` applies to integration 701062a. SHA256: `33ed86b22e6412d7cdccad3ccc0a4b16a93c6418b3db64cea7a70c88ab1671f4`. Seven code/test files only; no GIS exports or inventory CSVs. `git apply --check` passed against the integration worktree without changing it. The clean archived copy on Hopper needed `git apply --ignore-space-change` because the archive retained CRLF contexts.

The patch identifies native Class-50 and explicitly tagged synthetic connectors, excludes them before raster intersection, asserts physical-only exposure at aggregation/damage, and rejects contaminated legacy connector flood states during recovery. Virtual depths use a documented non-applicable zero sentinel with an explicit applicability flag. Physical access roads remain exposed. Both passenger and truck virtual speed caps remain unrestricted.

Clean integration qualification: Hopper job 3796660, exit 0, **14 tests passed** in 61.99 seconds; one rasterio warning. Runtime `/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_virtual_review_701062a`. Log `/scratch/akothaw/multimodal_hazard_data/stage2_scripts/ab_connector_pilot_20261118/clean_review_3796660.log`.

The tests use the integration worker's public initialization interface. Endpoint-only solver behavior remains tested independently on the experimental branch; this exemption patch does not introduce that routing change or C+S/G allocation. These features require separate integration review before the native-connector envelope can run. Stage 1 needs no additional exemption-only edit: connectors remain routing links; exemption is at hazard exposure, aggregation, pricing and recovery.

Matched recovery qualification: 3795089 (Harvey-15 control), 3795090 (Harvey-15 G), 3795091 (CONUS control), 3795092 (CONUS G). All use isolated pre-rebase revision 4409abf. Required gates: unchanged physical hazard/capacity/speed states; unchanged direct physical damage within 1e-9 relative; all 3,795 virtual links retained/unrestricted; zero virtual exposure; zero shortcuts in all twelve recovery path exports per run. No baseline rebuild or loading-point move is part of this qualification.

Owner confirmation is required before an integration merge. No integration push/merge has been performed.
