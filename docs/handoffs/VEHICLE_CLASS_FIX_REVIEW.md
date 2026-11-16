# Vehicle-class and demand-scope fix: review before merge (2026-11-15)

Branch `fix/vehicle-classes`, local only, off `feature/anaheim-assignment-diagnostics`. Not pushed, not merged. For the owner to review.

## Goal
Stop costing every demand as a passenger car, add the owner's truck factor for combined runs, record the demand scope, and prepare county-specific commute occupancy.

## What changed
| Change | Where |
|---|---|
| Vehicle class follows the demand: freight-only `ogv`, passenger-only `car`, combined `car` on PCE-weighted flow; override `RESIFLOW_VEHICLE_CLASS` | `src/resiflow/demand/vehicle_class.py`, `scripts/1_network_flow_model_revision.py`, `scripts/4_rerouting_and_recovery_scenario_loop.py` |
| Truck PCE 2.0 (parameter `assignment.truck_pce`), applied only when both classes share an assignment; vehicles reported unchanged; freight rerouting and isolation cost divided by the factor (PCE is capacity-only) | `src/resiflow/demand/combine.py`, stage 4 share and edge-flow reporting |
| Scope note (daily freight; one-way commute; no intrazonal; later additions) | `parameters/unified_parameters.json` (`_comment_scope`), `docs/ASSUMPTIONS_REGISTER.md` F7 to F10 |
| ACS B08301 occupancy script: all counties in one call, no-carpool crash fixed, per-all-worker factor | `scripts/commute_occupancy_acs.py`, `src/resiflow/demand/county_commute.py` |
| Passenger-only job sets the car class | `experiments/pass_a_convergence/hopper/submit_passenger_baseline.slurm` |
| Tests | `tests/test_vehicle_class_and_pce.py`; re-pinned toy and Sioux Falls values |

## Regression evidence
With `RESIFLOW_VEHICLE_CLASS=car` and `truck_pce=1.0` the old pinned toy and Sioux Falls values reproduce exactly, so these two settings are the only behavior changes.

## Expected effects on results (re-pinned values)
- Toy three-parallel: freight rerouting 67.32 to 76.10. Pure allocation: freight load share 0.77 to 0.87. Physical check: 10.43 trucks x 2 + 3.13 cars = 24 car equivalents, the edge capacity.
- Toy Braess: freight 46.9 to 327.4, passenger 50.8 to 177.3. The shared load rises from 25 to 37 car equivalents, so the detour congests. Very sensitive to the truck factor.
- Sioux Falls: freight rerouting 995.6 to 1,991.1; passenger unchanged.
- All Harvey and Sandy freight results used car costs. Freight-only runs now use the truck class, so every freight result needs a rerun to compare.

## Open items
- The 2.0 truck factor is an owner choice, unsourced.
- Combined runs cost the PCE-weighted flow as cars: a single-cost approximation. True multi-class needs engine support.
- Sealed fuel table now wired (2026-11-16): car $0.187/mi, ogv $0.6022/mi, constant (flag `cost_operating.use_table_avg_fuel_voc`, false = old curve). `manifest.csv` still calls the file documentation-only; the file header says sealed for Wave-1, and its values differ from the old curve (about 5% higher on Sioux Falls reroute cost). lgv/psv/rail keep the curve.
- The Census API key was rejected ("Invalid Key"; new keys must be activated from the signup email). County occupancy is therefore not yet generated.
- Stage 4 still has no passenger-only mode.
- Isolation cost has three monetisations (T00 $280 per worker-day, parameter $50 per day, stage 4 value of time x 24).
- OD payload: register F1 says a flat 20 t per truck; the adopted table T29 gives 19.39 t.
- `tests/test_asset_length_costing.py` fails at collection (stale: `compute_damage_values` removed). Pre-existing, not touched.

## To merge (only after owner confirmation)
Fast-forward into `feature/anaheim-assignment-diagnostics`, push, delete `fix/vehicle-classes`. Update the `AGENTS.md` ledger.
