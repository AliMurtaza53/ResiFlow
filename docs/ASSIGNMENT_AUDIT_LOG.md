# Assignment iteration audit log

`network_flow_model` (`src/resiflow/road_revised.py`) logs two extra line types per iteration. They are additive: existing lines are unchanged (`parse_assignment_log.py` output is identical with and without them).

## Why

The older `Iteration progress: assigned_delta` and `Pass A convergence: assigned_fraction` lines measure the drop in `remain_od`. That drop includes demand moved to `isolated_od` after edges were deleted, so those lines overstate delivery. On Anaheim at 40x demand, `assigned_fraction` reaches 0.990 at iteration 12 while the delivered fraction is 0.684. Use `ITER_AUDIT` for delivered flow.

## `ITER_AUDIT` (parse by key, not position)

```
ITER_AUDIT iteration=<k> delivered=<f> delivered_cum=<f> delivered_frac_cum=<f>
  isolated_structural=<f> isolated_congestion=<f>
  isolated_structural_cum=<f> isolated_congestion_cum=<f>
  remain=<f> remain_frac=<f> edges_deleted=<int|NA> origins_no_out_edges=<int> iter_wall_s=<f>
```

- `delivered`: flow actually loaded this iteration (the `Post-realization assigned_iter_sum` value).
- `isolated_structural`: demand with no path, or an absent node, at iteration 1.
- `isolated_congestion`: the same at iteration 2 or later, i.e. after edges were deleted.
- `remain`: demand still in `remain_od` after the iteration.
- `edges_deleted`: edges pruned this iteration; `NA` on stop iterations, where no pruning runs.
- `origins_no_out_edges`: distinct origins still in `remain_od` whose vertex has no outgoing edge (or is absent).

## `INVARIANT` lines

```
INVARIANT conservation ok=<bool> iteration=<k> residual=<f> tol=<f>
INVARIANT capacity ok=<bool> iteration=<k> violating_edges=<n> max_overshoot=<f>
```

- conservation: `initial - (delivered_cum + isolated_structural_cum + isolated_congestion_cum + remain)` must be within `RESIFLOW_INVARIANT_REL_TOL` (default 1e-6) times initial demand.
- capacity: no edge's residual `acc_capacity` goes below zero beyond a 1e-6 relative tolerance.
- Violations log at WARNING. Set `RESIFLOW_INVARIANT_RAISE=1` to raise `AssertionError` instead.

## Knob

`RESIFLOW_EDGE_PRUNE_RATIO` (default `0.01`, range 0 to 1): an edge is deleted when its residual capacity is below 1 vehicle or below this fraction of its original capacity.

## Anaheim reproduction

`parameters/testbeds/anaheim.json` with `demand_scale` raised: 1x and 3x finish in 1 iteration; 6x in 3; 10x in 6; 20x in 9 (94.2% delivered); 40x in 14 (68.8% delivered). Tests: `tests/test_assignment_audit.py`.
