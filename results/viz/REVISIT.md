# Figure review (advisor comments, 2026-10-22): resolved vs. to revisit

## Resolved with the reconciled synthetic model (`figlib/synthetic_model.py`)
- Event totals now reconcile by construction: RQ1_1 class bars sum to Direct per event; RQ1_2(B) = RQ2(B) state sum (states + Rest) = Direct + 90-day indirect; RQ2(A) mode bars sum to the indirect part; RQ1_2(A) state bars are leading-state Direct and no state exceeds its event total.
- RQ1_1: classes are mutually exclusive (bridges are split out first, as an asset-type bar); earthquake road classes are $0 by design (bridges only). 3 displayed severity levels = minor, moderate, severe+extensive (state this in the caption).
- Horizon: indirect costs labeled cumulative 90-day (RQ2 A axis). RQ1_2(B) total = Direct + that cumulative indirect.
- Denominators explicit: per *exposed* lane-mile (RQ1_2 C), freight-only cost / annual freight value in the affected area (D), per capita in affected counties (E). Placeholder denominators: lane-miles 52k/61k/58k/98k, population 6.9/11/9/38 M, freight value $60/45/38/120 B.
- RQ3: "cargo value" (tons x FAF5 $/ton), not cost; panel C sums to panel B per event. Titles/axes updated; error-bar axis label says "mean with min-max range".

## Still open (cannot be fixed by editing synthetic data)
1. Real totals do not exist yet: converged baseline (only 11% of demand assigned) and re-runs of Harvey, New Madrid, NM landslide, Sandy, Cascadia.
2. Dollar year: axes say 2023 but model components are 2026 Q1 (Direct), 2022 (VOT), 2023-24 (fuel), 2017 (FAF value). Harmonize or relabel (registry columns `axis_dollar_year`, `dollar_year_by_component`).
3. Recovery horizon in real data: runs are day-0..90 checkpoints of daily rates; need integration to a stated window.
4. Indirect-cost state attribution rule (origin state assumed in the placeholder); passenger output is off in real runs; Toll is $0.
5. RQ1_1 needs a real road-class split of Direct and the 5 -> 3 severity mapping documented; bridge overlap rule.
6. Lane-miles: exposed vs damaged vs statewide, directed links; population: footprint vs county vs state; real denominators.
7. Error bars: define the source (damage-ratio min-max band vs ensemble vs bootstrap). Placeholder uses a +/-12% min-max band.
8. RQ3: validated commodity totals and baseline denominators; large disrupted share may just reflect large baseline share (exposure ratio plot kept as a supplementary prototype).
9. Placeholders that look like findings should be removed or flagged before submission (e.g. Harvey/NM landslide event identities).

## Update (RQ1_1)
- Earthquake road classes are now shown non-zero in the placeholder (no empty class rows). This conflicts with the model, where earthquake road damage is $0 by design (HAZUS bridges only): reconcile before real data.
- Damage intensity: minor/moderate/severe does not map the same way across hazards (depth for flood, PGA/Sa for earthquake, PGD for landslide, ice/snow for winter storm; model ladder has 5 levels). Need a hazard-consistent intensity normalization or per-hazard severity definitions; the figure currently shows the 3-level display only as a layout example.
