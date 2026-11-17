# Test 2b gateway pilot

Start with Long Beach centroid 100174, LA Harbor 100178, and Houston 100146. The verified official connector links are 219923, 225343 and 225344, and 633909, respectively. Long Beach and Houston link directly to named seaport nodes. LA Harbor uses the existing port-complex label and its two original road attachments.

Budget one localized Harvey-15 gateway arm against the existing mean-parent C+S control. Keep the Test 2a endpoint-only executable, physical graph, payload, and routable scope fixed for this comparison. Reconstruct imports and exports by FAF zone pair and commodity. Move eligible import origins and export destinations from their existing C+S endpoints. Cap each direction and zone at available demand, preserving the published relative shares across the selected gateways. Keep all other legs unchanged. Use a mean weight for missing parent flow records.

Check pre-allocation county OD coverage and post-allocation conservation at 1e-9 relative tolerance. Require matched weighted mean haul within 2%, zero non-endpoint centroid paths, positive assigned connector load at the three gateways, shared physical capacity respected, and no worse unassigned demand. Report if a directional target exceeds the available demand. Diagnose first physical-road access flow and capacity, and use official road-link agreement as a diagnostic. Freight-only capacity is a screening result. The combined freight and passenger test must recheck binding links at the gateway exits.

Expand inventory coverage to all 255 facility-range IDs only after the pilot passes. Published zeros and missing records remain distinct. Expansion does not force positive demand at every ID. Full-CONUS and Harvey-15 stages 1 through 4 use the current integrated freight vehicle and fuel settings with matched controls.

## Preflight and assignment

The builder reconstructed the relevant FAF zone-pair, commodity and market cells from the FAF5.7.1 regional data and BTS county factors. For the pilot it used the same domestic truck mode, 20-ton payload and original inter-county pairs as the mean-parent control. It withdrew each moved trip from the corresponding C+S endpoint pair before inserting it at a gateway. All other legs retained their existing endpoint shares.

| Gateway centroid | Official import / export targets (trips/day) | Allocated import / export (trips/day) |
|---|---:|---:|
| Long Beach 100174 | 1,911.28 / 956.01 | 1,829.95 / 956.01 |
| LA Harbor 100178 | 4,695.51 / 1,069.45 | 4,495.70 / 1,069.45 |
| Houston 100146 | 4,441.79 / 5,894.17 | 3,569.86 / 5,894.17 |

Both import zones exhausted the eligible Harvey-15 input, and their combined national FAF targets were scaled down to 6,325.65 for LA/Long Beach and 3,569.86 for Houston. Both export targets fit within the available volume. In all, 17,815.14 existing trips/day changed endpoints, 2.36% of Harvey-15 routable demand. The final OD contains 2,072,948 rows and 754,974.302225 trips/day, matching the control. Mean geodesic haul increased from 174.7201 to 174.8016 mi (+0.047%). The ±2% go interval was 171.2257–178.2145 mi.

Hopper baseline job `3784230` uses output variant `harvey15_connector_test2_gateway_pilot`. It compares every physical road capacity against the mean-parent control and reports volume-to-capacity on physical roads incident to each gateway's official road attachments. The separate shortcut audit verifies the paths. Staged OD and gate artifacts are under `stage2_scripts/connector_test2_gateway_pilot/` on Hopper.

## Pilot result and expansion gate

Job 3784230 completed in 17m 10s. It assigned all 754,974.302225 trips in one pass with zero binding links, zero unassigned trips, and zero shortcuts across 2,072,948 paths. Assigned connector flows were 2,785.96 at Long Beach, 5,565.15 at LA Harbor and 9,464.03 at Houston. Maximum volume-to-capacity on roads incident to their road attachments was 3.4%, 5.3% and 9.0%, respectively. Against the mean-parent control, Pearson road-link correlation rose from 0.5305 to 0.5690 in LA, from 0.4949 to 0.5354 in Harris, and from 0.4673 to 0.4706 on all 312,073 matched road links. This cleared the freight-only pilot gate.

For broader coverage, use each gateway's native FAF zone and directional market flows. Preserve original regional zone-pair, commodity and market totals and the first-pass original routable scope. Apply the same available-demand caps and keep explicit zeros and missing records separate. Use the same integrated freight vehicle class, fuel costs, capacities and inputs on each matched C+S and C+S+G pair. Budget one input preparation job, four profiled baselines and a dependent stages 2–4 job per baseline. Stop any recovery chain if its baseline verification fails.

The first expansion prep failed the OD support check because zero-trip factor rows could create keys absent in the saved control. It created no assignment inputs. After removing zero-trip rows from that check, Hopper job 3784289 passed.

| Scope | Original routable trips/day | Moved to gateways/day | Mean haul control → G, mi | Allocated gateways / in geographic scope |
|---|---:|---:|---:|---:|
| CONUS | 1,510,749.56 | 100,886.86 | 193.1300 → 193.8684 | 238 / 244 |
| Harvey-15 | 754,974.30 | 61,480.98 | 174.7201 → 175.6595 | 114 / 116 |

Each coverage manifest contains all 255 IDs. CONUS excludes 11 out-of-scope gateways and leaves three explicit-zero and three unreported in-scope gateways unloaded. Harvey-15 excludes 139 out-of-scope gateways and leaves two unreported in-scope gateways unloaded. The freight-only access check does not substitute for a combined freight and passenger binding-link check.

## Expanded assignment and recovery jobs

All jobs use the pinned integrated experiment checkout at `19b02b1`. The G baseline waits for its matched C+S control and verifies its physical road capacity against that control. Each recovery runs stages 2, 3, 3 postprocess, and 4 only after its baseline succeeds. Results are separated by scope and arm.

| Scope | Arm | Stage 1 baseline | Stages 2–4 |
|---|---|---:|---:|
| Harvey-15 | Mean-parent C+S control | 3784300 | 3784301 |
| Harvey-15 | C+S+G | 3784302 | 3784303 |
| CONUS | Mean-parent C+S control | 3784304 | 3784305 |
| CONUS | C+S+G | 3784306 | 3784307 |

The first attempt to generate the complete Slurm chains stopped before submission because one template used a relative code path. The retry verified all scripts with `bash -n` and submitted the jobs above.
