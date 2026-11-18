# A/B connector pilot preregistration — 2026-11-18

Status: decision rule fixed before any A/B pilot assignment result. No freeze is authorized by this document. Arm C is deferred.

## Authority and scope

The owner's direct message authorizes running the A-vs-B pilot and supersedes the older note's restriction on new Hopper submissions. No integration merge/push or branch deletion is authorized. Canonical AGENTS.md was updated first; the experiment copy was synchronized from it.

Named counties: Los Angeles / Long Beach 06037, Harris TX 48201, Clark WA 53011. Additional barrier/coastal examples are Brazoria TX 48039 and Chambers TX 48071. Their selection is fixed now; candidate placement must not use the hazard raster or resulting isolation.

A is current official C+S+G loading with the virtual-hazard exemption. B adds screened access alternatives at EXISTING loading units, preserving the entire OD. There is no new within-county demand split and no change to C/S/G margins. The named counties alone may receive new access; national road topology, road IDs/capacities, demand elsewhere, vehicle/fuel settings and hazard inputs remain fixed.

Freight-only primary runs use the full saved CONUS G OD, 1,510,749.556669 trips/day. Combined runs add the corrected connected passenger split OD, 51,718,653.8941 cars/day, with truck PCE 2.0. Passenger road loading points in the five counties need separate virtual endpoint aliases in BOTH arms so physical through-roads never become prohibited centroid-transit nodes. A's alias attaches to the existing point; B may add alternatives. Shared/ambiguous county-road nodes cannot be silently attributed or split.

## Materiality: fixed numerical rule

For county i, snapshot d in {0,7,14,30,60,90}, demand case m in {freight,combined}, and OD end e in {origin,destination}, compute isolation I and incremental rerouting cost C separately. Never sum origin and destination figures as unique trips.

I is total undelivered input demand: baseline isolation PLUS additional post-hazard isolation among baseline-delivered trips. These sets must be disjoint. Report the two components separately as well. Using hazard-only isolation would otherwise reward a network that failed to serve more demand before the event. Residual solver demand at an iteration cap is not silently added to physical isolation; it fails the convergence/accounting gate. Rerouting cost C remains incremental cost for successfully routed disrupted demand, with the served-cohort difference disclosed.

An isolation effect is material iff:
  abs(I_B-I_A) / max(abs(I_A), 100 units/day) >= 0.05.

A rerouting-cost effect is material iff:
  abs(C_B-C_A) / max(abs(C_A), 10,000 USD/day) >= 0.05.

Thus ordinary controls use a 5% relative threshold; near-zero controls require at least 5 isolation units/day or $500/day. Equality counts as material. In freight, isolation units are trucks/day. In the combined solver, the primary capacity-flow measure is PCE/day, explicitly labelled; separate vehicle counts may be reported where the existing proportional class accounting supports them. Do not label PCE as vehicles.

Direction of change does not matter: increased impacts can also expose material sensitivity. Costs exclude direct asset damage and isolation valuation. Compare each arm's damaged-network paths with its own matched intact cohort; changing OD identifiers between arms is not allowed.

County attribution: official C/S uses its parent county. G uses its explicitly identified facility host county and is labelled as such, not the unknown original displaced county. Unresolved facility hosts or shared passenger nodes remain separate uncertainty buckets; they may not be assigned by nearest county to fill a table.

Primary B targets up to FOUR credible total exits per loading unit, retaining original exits. Fewer exits are allowed only with explicit rejection reasons. The county coverage gate requires at least one positive-demand loading unit with an added valid exit in each named county. A county with no credible modification is an unresolved coverage case, NOT evidence of no material effect.

## Decision

After all mechanical/coverage gates pass, any primary county/end/day/case reaching either materiality threshold selects B for the envelope. Otherwise select A and report the B range and single/few-connector limitation. Do not tune thresholds, candidates or costs after inspecting outcomes. Failure of mechanical or coverage gates selects NEITHER network: fix or report the unresolved test, with no freeze.

Convergence and loading-point saturation are additional diagnostics. Do not require B to improve delivered demand. A freight arm already assigning in one iteration cannot establish a convergence benefit.

## Candidate constraints fixed before assignment

Reuse existing connector-insertion eligibility utilities. No ramps, freeway mainline, bridge/tunnel midspan, disconnected stubs, or cross-county attachment. Physical roads may not be split or duplicated in this pilot.

New area-centroid exits must be local to an existing valid attachment (maximum 3 km routed local access and 2 km straight-line distance), reachable without a bridge/tunnel crossing, and within the same bridge-free physical block as an existing exit. This prevents a new synthetic link from bypassing a genuine static cut edge. Exits must be at least 150 m apart. Existing native exits and their access cost remain unchanged. New access speed is 25 mph, matching the existing FAF experiment, with positive length based on access distance; no zero-cost distant exits.

These are screening assumptions for an aggregate loading area, not proof of an unmodelled local road. G alternatives additionally require an appropriate native facility reference in the same facility complex; otherwise retain its original exits and report the exception. Do not manufacture facility gates. Every candidate retains its geometry, eligible physical edge, component/block, access distance/cost, evidence and accepted/rejected reason in GIS.

Generate nested 2/3/4-exit candidates and a deterministic alternate placement/cost screening diagnostic (15 versus 25 mph for added access only). These lower-cost geometry/path-time sensitivities are reported separately; they do not replace the primary four-exit capacity/recovery comparison or drive network selection. No demand-weight perturbation is allowed in A/B; that belongs to deferred Arm C.

## Gates, hazards and budget

Prerequisite: all four existing exemption reruns 3795089–3795092 pass physical-state/damage and recovery path verifiers. Prepare the clean exemption change set independently of the pilot.

Hard pilot gates: OD conservation at 1e-9 relative, zero centroid shortcuts, zero virtual exposure/restriction, valid baseline physical component, unchanged physical road capacities/IDs, unambiguous loading mapping and credible access evidence. Synthetic connector capacity must not be counted as duplicated physical capacity.

Use Harvey event 1 / scenario 304 with the same six recovery snapshots. This exposes the Texas counties directly; LA and Clark results primarily test congestion and trips through the disrupted region, not local Harvey exposure. Report this scope limitation; do not claim local hazard robustness in WA/CA.

Budget: at most EIGHT new compute submissions: one input/candidate preparation+screening job; freight B baseline+stages2–4 (2); combined A baseline+stages2–4 (2); combined B baseline+stages2–4 (2); one comparison/report job. Freight A reuses the existing baseline and successful corrected full-CONUS G recovery 3795092. Any numerical behavior equivalence needed after rebase must be checked before reuse.

Baseline/recovery jobs use eight CPUs, up to 600 GB and a six-hour wall cap, fixed equally within each matched demand case. Freight uses the original 15-iteration cap to match reused A; combined uses 40 in both arms. Hitting a cap with residual solver demand is an unresolved convergence case, not successful assignment or physical isolation. Preparation/comparison use at most four CPUs, 64 GB and one hour each. Hard maximum requested CPU envelope: 296 CPU-hours (6*6*8 + 2*1*4); actual time should be lower. No automatic budget extension or national rollout.

Outputs use isolated pilot variants and a manifest. Original baselines, original recovery artifacts and the GIS review package remain untouched. Stop on a failed gate, do not manufacture a successful comparison, and do not freeze either network before reporting.

### Preflight implementation corrections, before assignment

Pending preparation job 3796589 was held before it ran: code review found a geometry-only reader being used for a non-geometry column projection. Use the ordinary parquet reader instead. Its replacement is a setup retry, with zero compute consumed by 3796589; the eight analysis-job slots and 296 CPU-hour cap remain unchanged. Source snapshots are preserved rather than edited under a queued/running job.

Input totals above include same-node trips. The existing shared assignment deliberately excludes these from road routing. The preflight now records these quantities explicitly and checks solver conservation against inter-node demand; this does not delete or redistribute any input OD. Combined costs remain the existing single-cost, PCE-weighted approximation, not separately estimated passenger and truck welfare costs.

Freight A reuse check: `git diff 19b02b1 HEAD -- src/resiflow/road_revised.py src/resiflow/demand/combine.py src/resiflow/demand/vehicle_class.py src/resiflow/parameters.py` is empty after rebase. The new explicit freight demand-case selects the same freight loader. Passenger-only aliases are appended to both networks with no freight OD at them. Endpoint-only routing prevents those unused endpoints from becoming shortcuts; original graph edges and order are retained. No freight-A baseline code, cost parameter or OD change is introduced by reusing the saved assignment.
