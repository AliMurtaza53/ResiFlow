# Commodity split of freight results (plan, 2026-11-26)

Status: plan only. Nothing here changes the frozen network A inputs or the envelope runs.

## Why this is needed
The frozen freight OD (`freight_od_T29_gateway_conus.pq`, 1,596,299.49 trucks/day) has columns `origin_node, destination_node, Car21` only. The assignment is commodity-blind (same routing, flat $50 per isolated truck), so every Stage 4 output is per origin-destination pair with no commodity. RQ3 (cost by industry) needs a commodity split.

## Key finding: the split is exact, no assignment rerun
Every step from the by-commodity FAF5 matrix to the frozen OD is linear in trips per commodity group (`sctgG5`):
1. `rebuild_faf_od_payload.py`: scale each row by 20 / T29 payload of its group, sum by node pair, remap and drop AK/HI. Per-row and per-pair, so linear.
2. `prepare_faf_conus_subcounty_od.py` (mean weights): `allocate()` sets `trips = Car21 * out_share * in_share`. The shares depend on the endpoints only.
3. `prepare_faf_gateway_pilot.py`: cells already carry `sctgG5`; one scalar `fraction` per zone and market is applied to every commodity. Withdrawals and additions are aggregated by node pair, which is where the commodity key is lost. The only nonlinearity is `clip(lower=0)` on the pair difference, which matters at the 1e-9 level.

So final OD by commodity k = C+S baseline_k - withdrawn_k + added_k. Summed over k it must equal the frozen OD.

## Steps
1. Rebuild: also write the per-commodity conterminous OD (key: origin, destination, sctgG5).
2. Subcounty allocation once per commodity (allocate is linear), or loop inside the script.
3. Gateway pilot: carry `sctgG5` through `county_pairs`, `withdrawn`, `deposited`; write a per-commodity final OD with a `sctgG5` column.
4. Gate: sum over commodities equals `freight_od_T29_gateway_conus.pq` per pair (rtol 1e-9) and in total; sha256 of the frozen file unchanged.
5. Apply the shares to Stage 4 outputs, per OD pair:
   - isolation: `trip_isolations_*_day*.csv` (origin, destination, Car21, isolation_cost_usd);
   - rerouting: per-path files `odpfc_freight_s1_day*.pq` minus their `_baseline.pq`.
6. Add `commodity` rows to `results_long.csv` and build the RQ3 panels.

## Not covered
- Direct infrastructure damage cannot be assigned to commodities.
- If commodities should route or be valued differently, the model needs separate commodity classes in every run (about 5x compute); this plan does not provide that.
- Gateway flows (about 6% of trips) are commodity-resolved by step 3 because the gateway step already works by group.

## Cost
About 1 to 2 days of development including the sum gate, plus a few hours of Hopper batch time. No Stage 1 to Stage 4 reruns.
