# Test 2a full-CONUS first-pass comparison

Use the full corrected CONUS freight input from job 3710402. Route the original non-self OD demand in three arms on the same endpoint-only network and executable revision. The parent-only arm is the matched control. The two C+S arms use zero or mean sub-county weight for a missing parent record, matching the Harvey pilot. Facility-range allocation is outside this comparison.

The nine Connecticut planning-region keys without exact official parents retain their eight existing road nodes in every arm. Preserve each original OD pair to 1e-9 relative tolerance and the 1,510,749.556669 routable trips/day. The first-pass weighted geodesic mean must be within 2% of the corrected-road reference. The original same-node demand stays outside all assignment arms.

Budget one preparation job, three profiled first-pass assignment jobs, and one link-comparison job. Keep road capacities, path weights, access settings and eight CPUs fixed. Require full first-pass assignment, no binding capacity, zero centroid shortcuts and positive flow at intended centroids before calling the saved flows all-or-nothing. If any arm fails, report the gate and do not label its post-capacity flows unconstrained.

Report matched link counts and coverage, Pearson correlation, weighted absolute error, summed link traversals, and class and county breakdowns. Use one common link support, include published zeros, and count missing official rows separately. Report capacity and connector-network differences, CONUS geography, FAF demand and payload differences, and FHWA path choice versus ResiFlow single least-cost path. Correlation on road links is a diagnostic. Connector agreement partly reflects the weights used to allocate demand.

## Reference and job records

The prior corrected-road-node CONUS first pass (3710402) had zero binding edges and assigned all 1,510,749.556669 routable trips. Its Pearson correlation was 0.5531 over 312,073 shared road links with published records, with modeled-to-published summed link traversals of 1.2811. It is an external reference for this experiment. The new parent-only arm uses the same restored connectors as the C+S arms.

The restored model uses the 483,599 native road link IDs in the converted graph and the 3,795 Class 50 connectors. Its road ends use the checked Hopper node crosswalk and physical capacities are shared across directions. The endpoint-only rule applies in all three arms. The Connecticut exception leaves both loading and geography fixed for approximately 12,719 routable trips/day touching those eight road nodes. The corrected demand excludes Alaska and Hawaii, even though the graph extends beyond the CONUS demand area.

The public FAF22 comparator supplies modeled link trips, including markets that ResiFlow distributes differently. ResiFlow's audited county OD used a flat 20 tons per truck. FHWA models payload by commodity, haul and vehicle type, and routes modeled trucks using path choice over alternatives with travel time and tolls. ResiFlow assigns a single least-cost path per OD on the first pass. Treat link-flow sums as traversals and give volume bias and flow correlation separately. See the [BTS assignment archive](https://rosap.ntl.bts.gov/view/dot/88267) and [FHWA assignment method](https://ops.fhwa.dot.gov/freight/freight_analysis/faf/faf5/FAF5_FHWA_Webinar2_Highway_Assignment_October20.pdf).

Initial prep job 3765545 exited 127 because the compute-node profiling fallback could not find Python on PATH. Its dependent assignments were cancelled before launch. The retry includes the environment's bin directory and uses a separate job manifest.

| Job | Hopper ID |
|---|---:|
| Input preparation and haul/conservation gate | 3765684 |
| Matched parent-only first pass | 3765685 |
| C+S first pass, zero for missing parent | 3765686 |
| C+S first pass, sub-county mean for missing parent | 3765687 |
| Comparison after all three pass | 3765688 |

Hopper inputs and comparison tables are under `/scratch/akothaw/multimodal_hazard_data/stage2_scripts/connector_test2_conus/`. Each assignment has its own result variant and database. Comparison output is `faf_comparison.csv` in the experiment directory.

## Completed input checks

Job 3765684 completed. The corrected-road reference had 9,653,612 inter-node rows and a weighted mean geodesic haul of 193.1203 miles. The go window was 189.2579–196.9828 miles. All three arms preserved every input row's flow at roll-up and retained 1,510,749.556669 routable trips/day.

| Assignment arm | Input rows | Geodesic haul, miles |
|---|---:|---:|
| Parent only | 9,653,612 | 193.0668 |
| C+S, missing parent zero | 9,998,234 | 193.1507 |
| C+S, missing parent mean | 10,284,594 | 193.1300 |
