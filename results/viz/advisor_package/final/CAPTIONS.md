# Caption sheet for writing (generated from visual_registry.csv; values in the figures are PLACEHOLDERS)

## RQ1_1  (RQ1_1.pdf / RQ1_1.png)

- **Panel(s) -: Direct cost by road category, per hazard**
  - Caption draft: Direct infrastructure damage cost, divided into Minor, Moderate, and Severe components, across five road categories for each event.
  - Dollar basis: axis 2023; Direct = NHCCI-escalated unit costs (CP25 road 2018 Q4, T30 bridge 2024 Q4, tunnel 2008 Q4) to code default 2026 Q1 (resiflow/nhcci.py). Axis says 2023: harmonize every component to 2023 (NHCCI target year + CPI for VOT/fuel) or relabel before publication
  - State in text: 2026-10-22: Figure = RQ1_1. Model severity ladder has 5 levels (minor..severe incl. extensive); figure shows 3. Earthquake roads are $0 by design (HAZUS: bridges only; Mineral EQ direct is $0 today). Road classes should follow hpms_fclass (local = 0.4% of links); a Bridges bar overlaps road classes.

## RQ1_2  (RQ1_2.pdf / RQ1_2.png)

- **Panel(s) A: (A) Direct Costs by Top States**
  - Caption draft: Direct infrastructure damage cost for the leading states under each event, with error bars.
  - Dollar basis: axis 2023; Direct = NHCCI-escalated unit costs (CP25 road 2018 Q4, T30 bridge 2024 Q4, tunnel 2008 Q4) to code default 2026 Q1 (resiflow/nhcci.py). Axis says 2023: harmonize every component to 2023 (NHCCI target year + CPI for VOT/fuel) or relabel before publication
  - State in text: 2026-10-22: Figure = RQ1_2(A). Error bars are not model uncertainty (single deterministic run); relabel as Direct min-max band or link bootstrap. Top-3 preview; registry asks top-10. State lists are placeholders; Harvey footprint is TX only.

- **Panel(s) B-E: (B) Total Cost | (C) Cost per Exposed Lane-mile | (D) Freight Cost Relative to Annual Freight Value | (E) Cost per Capita**
  - Caption draft: Total hazard cost (Direct, Rerouting, Isolation) per event: (B) total, (C) per lane-mile, (D) relative to annual freight value, (E) per capita.
  - Dollar basis: axis 2023; Direct = NHCCI-escalated unit costs (CP25 road 2018 Q4, T30 bridge 2024 Q4, tunnel 2008 Q4) to code default 2026 Q1 (resiflow/nhcci.py) | Rerouting = time at USDOT VOT (2022$) + fuel at 2023-24 pump prices, tolls from FAF5 (year unstated); non-fuel op. cost off | Isolation = isolated flow x USDOT VO
  - State in text: 2026-10-22: Figure = RQ1_2(B-E). B mixes one-time Direct with daily indirect cost (define horizon). C needs damaged or footprint lane-miles, not statewide. D: numerator should be freight rerouting+isolation, not damage. E: needs affected-area population rule.

## RQ2  (RQ2.pdf / RQ2.png)

- **Panel(s) A: (A) Rerouting and Isolation Costs by Travel Mode**
  - Caption draft: Passenger and Freight rerouting costs, with Operating, Time, Toll, and Isolation components, shown together for each event.
  - Dollar basis: axis 2023; Rerouting = time at USDOT VOT (2022$) + fuel at 2023-24 pump prices, tolls from FAF5 (year unstated); non-fuel op. cost off | Isolation = isolated flow x USDOT VOT (2022$) x 24h (alt. $50/trip-day, unstated year). Axis says 2023: harmonize every component to 2023 (NHCCI target year + CPI for VOT/fue
  - State in text: Compact alternative to separate RQ2 A and B: one shared axis so the Passenger vs Freight gap is visible. Passenger blocked (flag off); Operating/Time/Toll split synthetic; Toll is $0 in real runs.

- **Panel(s) B: (B) Total Cost by Top States**
  - Caption draft: Total Direct, Rerouting, and Isolation cost for the leading states under each event, with a Rest category.
  - Dollar basis: axis 2023; Direct = NHCCI-escalated unit costs (CP25 road 2018 Q4, T30 bridge 2024 Q4, tunnel 2008 Q4) to code default 2026 Q1 (resiflow/nhcci.py) | Rerouting = time at USDOT VOT (2022$) + fuel at 2023-24 pump prices, tolls from FAF5 (year unstated); non-fuel op. cost off | Isolation = isolated flow x USDOT VO
  - State in text: 2026-10-22: Figure = RQ2(C), bar small-multiples fallback (Sankey layout still unresolved). Indirect cost has no state until an attribution rule (e.g. origin state) is chosen; N for Rest open. One shared x-axis label.

## RQ3  (RQ3.pdf / RQ3.png)

- **Panel(s) A-B: (A) Disrupted Freight Tonnage | (B) Cargo Value of Disrupted Freight**
  - Caption draft: Total disrupted freight by event, shown as tonnage (left) and value (right), with stacks showing the industry mix.
  - Dollar basis: axis 2023 (value panel; will change); Freight value = FAF5 value (2017$ constant) (FAF5 values are 2017$; relabeled 2023 for consistency in the prototype only, deflate or relabel before use). Tonnage: no price year
  - State in text: Proposed dual panel (user 2026-10-22). Tonnage is synthetic; value = tons x FAF5 national truck $/ton (real factors, 2017$). Ranking differs by metric (Mining 21% of tons, 0.6% of value; Mixed freight 13% of tons, 45% of value). Real disrupted tons need a pipeline output (current mix files hold flow shares only).

- **Panel(s) C: (C) Cargo Value of Disrupted Freight by Industry in Top States**
  - Caption draft: Disrupted freight cost by industry for the leading states under each event (five SCTG groups).
  - Dollar basis: axis 2023; Cost basis undecided (Direct cannot be split by industry); if flow-allocated rerouting+isolation: Rerouting = time at USDOT VOT (2022$) + fuel at 2023-24 pump prices, tolls from FAF5 (year unstated); non-fuel op. cost off | Isolation = isolated flow x USDOT VOT (2022$) x 24h (alt. $50/trip-day, unst
  - State in text: 2026-10-22: Figure = RQ3(B), becomes (C) if RQ3 A is the tonnage/value pair. Plot filter is cost_type=Direct, which cannot be split by commodity: redefine as disrupted flow, flow-allocated rerouting+isolation, or cargo value. Event-level mix JSONs exist; per-state mix is not produced yet.
