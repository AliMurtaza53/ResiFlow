# Prior Pass B evidence (DAFNI-NIRD clone)

Copied/summarized from `DAFNI-NIRD-clone/docs/passb_parallel_optimization_log.md` and
`experiments/passb_timing/*/parsed_timing.json`. Use as baseline before re-running Goal 1 on CONUS.

**Configuration:** Pass B (`event_candidates`), `MaxFlowIterations=1`, ~9.7M path rows, 3143 origins.

| Step | NumCpu | Wall (s) | LCP (s) | od_id (s) | Stream p1 | Stream p2 |
|------|--------|----------|---------|-----------|-----------|-----------|
| 0 baseline | 1 | 4859 | 1455 | 1188 | 549 | 1503 |
| 1 patch6 | 1 | 2608 | 1088 | 0 | 247 | 1225 |
| 4 @1 prod | 1 | 2537 | 1048 | 0 | 245 | 1198 |
| 4 @2 | 2 | 2572 | 838 | 0 | 393 | 1280 |
| 4 @4 | 4 | aborted | — | — | — | — |

**Production lock:** NumCpu=1, `NIRD_OD_ID_AT_INSERT=1`, `NIRD_POOL_MAX_TASKS_PER_CHILD=50`.

**Failures:**
- `NIRD_LCP_COLLECT_POOL_RESULTS=1` → MemoryError (~9.6M paths in RAM)
- NumCpu=4 → negative scaling (42% LCP after 96+ min, aborted)
