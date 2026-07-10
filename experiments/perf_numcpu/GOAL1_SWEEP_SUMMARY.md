# Goal 1 — Sioux Falls Pass A numcpu sweep

| num_cpu | wall (s) | LCP (s) | stream p1 | stream p2 | total sim | CPU frac | write (MB) | run |
|---------|----------|---------|-----------|-----------|-----------|----------|------------|-----|
| 1 | 5.603 | 0.0 | 0.08 | 0.06 | 0.9268250465393066 | None | 0.00 | `goal1_sioux_passa_cpu1_20260710_174059` |
| 2 | 2.581 | 1.1330792903900146 | 0.04 | 0.02 | 1.426598072052002 | None | 0.00 | `goal1_sioux_passa_cpu2_20260710_174109` |
| 4 | 2.508 | 1.0762884616851807 | 0.03 | 0.02 | 1.3524012565612793 | None | 0.00 | `goal1_sioux_passa_cpu4_20260710_174112` |
| 8 | 2.863 | 1.3160877227783203 | 0.04 | 0.04 | 1.6597445011138916 | None | 0.00 | `goal1_sioux_passa_cpu8_20260710_174115` |
| 16 | 2.939 | 1.4581761360168457 | 0.04 | 0.03 | 1.764341115951538 | None | 0.00 | `goal1_sioux_passa_cpu16_20260710_174118` |

**Saturation note:** fill after review — compare `cpu_frac` vs `num_cpu` and whether
`wall_sec` tracks `lcp_sec` or post-LCP streaming phases.
