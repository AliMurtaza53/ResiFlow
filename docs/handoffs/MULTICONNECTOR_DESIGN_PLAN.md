# Multi-connector design: critique and bounded test plan

Date: 2026-11-18. Proposal only; no automatic connector generation or OD relocation is enabled by this document.

## Assessment

A single road loading point for a large, heterogeneous county is often too coarse for local congestion and hazard isolation. Multiple credible connections are an appropriate improvement. Single-point loading can still be an adequate strategic approximation for some long-distance national-flow questions; the problem is fitness for this application, not a universal rule that every zone needs several exits.

Multiple connectors do not eliminate arbitrary placement, missing first/last-mile roads, inaccurate within-county demand geography, or shared physical bottlenecks. Four nearby exits feeding the same bridge are not four independent routes. A facility with one genuine gate should not acquire fictitious alternatives.

There are two distinct choices:

1. Alternative access for the SAME local origin/destination: several physically credible approaches and route choice among them.
2. Spatial allocation of DIFFERENT trips within a county: fixed origin/destination shares over local loading areas.

Giving one county centroid free access to distant exits conflates those choices. After a flood the entire county's demand can effectively migrate to the surviving side, although real origins did not move. This can overstate resilience. Fixing the hazard treatment of virtual links remains necessary even after multiple exits are introduced.

## Are automatic heuristics enough?

Enough to propose reproducible candidates and support a screening-level experimental variant; not enough, by themselves, to validate facility access, small-area demand, or disaster isolation.

Department for Transport TAG M3.1 sections 2.4.11–2.4.14 require connectors to represent actual access and avoid movement barriers. Research on connector selection reports that merely increasing the number does not remove instability under arbitrary selection:
- https://assets.publishing.service.gov.uk/media/6a033d074fb0713aa63ea802/tag-m3-1-highway-assignment-modelling.pdf
- https://doi.org/10.1016/j.trb.2012.07.006

## Representation

Preserve native C/S/G IDs and their provenance. Do not replace existing S centroids with a second unaccounted disaggregation. New loading units need a separate generated-ID namespace and a crosswalk back to the existing centroid and county.

Where multiple spatial loading units are justified, split an existing OD quantity Q_ij into Q_(ih,jk) = alpha^O_ih * Q_ij * alpha^D_jk. Each origin/destination share vector sums to one, so rolling back up reproduces EACH existing OD pair. Shares stay fixed during the hazard.

Use different evidence for passenger home/work ends and freight production/attraction ends. LODES block-level residence/workplace information can inform passenger weights if retained; county-only LODES aggregates cannot locate trips within the county. Freight weights need available industrial/employment/commodity/facility evidence, with published C/S/G directional margins retained as constraints. Employment alone is a proxy, not observed freight generation. Equal shares are an explicit sensitivity case, not the default claim of realism.

Each local loading unit may then have a few genuine access alternatives. G represents a facility/complex and needs gate-level access evidence; it should not be spread countywide.

## Candidate generator

1. Start from pre-event activity locations and road connectivity. Use 2–4 as an initial pilot target where plausible, not a forced universal count or maximum.
2. Exclude disconnected stubs, invalid truck access, barrier-crossing approaches, bridge/tunnel midspan attachments and arbitrary freeway-mainline access. Match connectivity to the actual solver graph rather than a raw directed-SCC filter.
3. Where a local routable street network exists, use actual access paths rather than Euclidean nearest-k nodes. HPMS line density alone does not supply routable local topology.
4. Score coverage of activity clusters, plausible local access time, geographic spread and network-path distinctness. Avoid several nominal exits at one interchange. Do not manufacture independence when all real routes share one bridge.
5. Preserve credible native exits. Prefer existing eligible nodes in the first pilot to keep physical link IDs and capacity unchanged. If later splitting a physical link is necessary, preserve serial capacity and length, maintain original-ID provenance, and revise published-flow aggregation accordingly.
6. Include first/last-mile travel cost. A virtual line is not evidence that omitted local roads are floodproof; retain that uncertainty or explicitly model physical approaches.
7. Select connections without seeing the hazard outcome. Do not tune points or weights to reduce isolation, improve convergence, or reproduce FAF link scores.

Every candidate must produce a GIS/audit row: original centroid, generated loading unit, attachment road node, connector ID, access cost, evidence source, coverage weight, connectivity, barrier/access checks, redundancy group, and acceptance/rejection reason. Counties with fewer than two credible exits get explicit exceptions, not fabricated links. Ambiguous or high-impact cases require spot checks.

## Bounded comparison

First complete the virtual-hazard exemption and its matched recovery comparison. Then use identical demand, costs, physical capacities and hazard rules for:

A. Current official C+S+G connections.
B. Additional credible exits at the existing loading units; existing OD endpoints unchanged.
C. Fixed spatial loading units plus credible local access alternatives.

This separates exit-choice benefits from within-county demand geography. Start with LA/Long Beach, Harris, Clark WA and representative rural/barrier-dependent counties. No immediate CONUS-wide generator rollout.

Mechanical gates:
- Each original OD pair conserves to 1e-9 relative tolerance.
- Zero centroid pass-through shortcuts; no duplicate physical capacity or unauthorized topology changes.
- Zero virtual-link hazard exposure or closures.
- Every positive-demand attachment is valid on the intended baseline geographic component.
- Single real gate, shared bridge and all-physical-exits-closed fixtures remain capable of genuine isolation.
- No implicit origin relocation to a dry exit across an inaccessible local barrier.

Diagnostics, not targets:
- Original ±2% straight-line haul comparison as a continuity screen, alongside actual physical route miles. A justified change in demand geography may require revisiting that screen; do not tune geography to force it.
- Loading-point V/C, assigned/unassigned demand, convergence, physical bottlenecks, route distance/cost, county isolation, and matched FAF road-flow bias/correlation.
- Perturb candidate placement, plausible demand weights and connector count. Report ranges rather than choosing the realization with the smallest damage or isolation.
- Freight-only AON runs cannot demonstrate improved congestion convergence when all arms already assign in one pass. The combined passenger/freight experiment is necessary.
- Record added nodes, OD rows, memory and compute. Avoid uncontrolled k-squared expansion of the full national OD; expand affected pilot endpoints first.

Advance only when geometry/access checks pass, sensitive high-flow cases are reviewed, remaining uncertainty is reported and runtime is acceptable. Better realism need not reduce congestion or isolation; those outcomes are not pass criteria.
