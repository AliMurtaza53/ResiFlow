# Virtual-link hazard exemption: clean review packet

**READY for owner review. No integration merge/push or network freeze.**

`virtual_exemption.patch` applies to **701062a** and contains eight code/test files, no GIS exports. SHA256: **3abb35379c6d2c04c6e12e2ea3d9490e135350f645c19037e47a8fba1c2520cb**. `git apply --check` passed against integration without editing it. On the archived Hopper copy, `git apply --ignore-space-change` handles the archive's CRLF contexts.

## Behavior

Native FAF Class 50 and explicitly tagged generated connectors are excluded BEFORE raster sampling for **flood, earthquake, landslide and winter storm**, while remaining routing links. Unknown physical road classes remain exposed. Aggregation and damage pricing reject stale virtual exposure records. Recovery checks virtual state before and after damage overlay for every hazard family. Virtual intensity/depth zeros are non-applicable sentinels with an explicit applicability flag; they are not measurements of a dry or unaffected facility. Physical approach roads remain exposed and capable of isolating demand.

The initial flood fix missed the separate shared intensity sampler. Final review closed that gap, added all-hazard legacy guards, and tested the non-flood builders against physical-only controls. The flood calculation validated by the four real reruns is unchanged. The old assert_centroid_flood_state name remains a compatibility wrapper for the shared state guard.

## Code qualification

Fresh integration copy: `/scratch/akothaw/multimodal_hazard_data/code/ResiFlow_virtual_review_allhazards_fixturefix_701062a`.

- Broad qualification **3798915**: **59 passed, 2 skipped**, plus one new winter fixture failure because required from_id/to_id topology fields were omitted. The six Sioux Falls end-to-end hazard cases passed.
- Fixture corrected; focused qualification **3798972**: **15 passed**, 17.18 seconds, job exit 0. All seven production files were checked byte-identical between the broad and focused copies. Only the test fixture changed.
- Together these validate **60 unique executed checks**; the 14 focused checks already passed in the broad run are not counted twice. The two skips are the real-network winter classification tests whose configured network parquet is absent in the clean copy. This does not claim a full-CONUS non-flood result qualification.
- Initial bootstrap **3798614** stopped before tests because /usr/bin/time was absent on its compute node; the retry used Slurm resource measurements. The earlier flood-only clean qualification 3796660 passed 14 checks and is superseded in scope by this packet.

See `allhazard_code_qualification.json` and the two retained logs. The first log intentionally preserves the fixture failure rather than concealing it.

## Real matched recovery qualification

`recovery_qualification.json` records all four pre-existing flood/Harvey chains:

- 3795089 Harvey-15 control: 1:09:12, exit 0.
- 3795090 Harvey-15 G: 1:26:31, exit 0.
- 3795091 CONUS control: 2:18:52, exit 0.
- 3795092 CONUS G: 2:48:26, exit 0.

All 483,599 physical hazard records were unchanged. All 3,795 virtual links were retained/unrestricted with zero exposure. Direct damage remained **$1,468,883,828.539848**. All **48 recovery solves** passed 1e-9 accounting/residual checks, all **48 path exports** had zero shortcuts, and no invariant failure was logged. These qualification runs are separate from the stopped A/B pilot budget.

## Integration limits

Stage 1 needs no exemption-only edit: synthetic links stay in the routing graph. This patch does NOT land C+S/G allocation, native-network loading overrides or endpoint-only shortest paths; those experimental features require separate integration review before the native-connector envelope. Tests use integration's public worker interface. Old contaminated hazard caches must be regenerated, not silently repaired. Non-flood national scenarios still need their fresh Stage 2–4 runs; the code qualification above is not a substitute for those outputs.

Owner confirmation is required before an integration merge. The failed A/B geometry-coverage gate is a separate unresolved decision and does not invalidate the exemption qualification.
