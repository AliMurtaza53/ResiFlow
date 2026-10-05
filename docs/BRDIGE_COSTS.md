Integrate tunnel construction-value and direct-damage estimation into the existing script using tunnel_cost_parameters.csv. Inspect the existing network fields, units, asset identifiers, and damage calculation before editing.

1. Load model parameters from the CSV; do not hardcode coefficients.
   Use highway_conventional for highway tunnels.
   Subway models apply only to actual rail/subway tunnels with a known
   excavation method. Flag highway tunnels outside the conventional
   model's scope rather than substituting subway equations.

2. Calculate at physical tunnel/bore level:
   - L = full bore length in kilometres.
   - For highways, D means excavated span in metres.
   - Prefer measured excavated span.
   - Otherwise use verified per-bore clear width + 2 * lining allowance.
   - Otherwise estimate:
     D = lanes_per_bore * assumed_lane_width_m
         + assumed_extra_clear_width_m
         + 2 * assumed_lining_m_per_side.
   - Lane and allowance defaults are analyst assumptions; record this.
   - NTI length G.1 is feet; convert using 0.3048 / 1000.
   - Grouped NTI records use longest-bore length. If individual bore
     lengths are unavailable, assume equal lengths and flag this.
   - Divide total lanes by bore count only when an equal split is
     reasonable; flag unequal splits for review.

3. Evaluate the selected CSV equation:
   If cost_form == "log10":
     cost_million_2008 =
       10 ** (intercept
              + length_coefficient * log10(L)
              + size_coefficient * log10(D))
   If cost_form == "linear":
     cost_million_2008 =
       intercept + length_coefficient * L + size_coefficient * D

   Sum bore costs for each physical tunnel. Bore-level application and
   summation are screening assumptions, not verified calibration details.

4. Convert to target-year USD:
   construction_value =
     cost_million_2008 * 1_000_000 * escalation_factor

   Make escalation_factor configurable. Default 1 means December 2008
   USD, not current USD. Prefer the paper's ENR CCI ratio to December
   2008; an NHCCI ratio is a disclosed alternative. Do not invent an
   inflation factor or escalate from publication year 2013.

5. Calculate direct damage:
   direct_damage_usd =
     construction_value * existing_hazard_specific_damage_ratio

   Reuse the existing damage model only if it applies to tunnels.
   If tunnel damage ratios are unavailable, report construction value
   and missing damage ratio; do not treat closure as 100% damage.
   Do not additionally multiply by damaged length if the damage ratio
   already represents whole-asset loss.

6. Deduplicate physical assets before summing direct damage.
   Multiple directed edges and segmented links must not each receive
   the full tunnel cost. Map the asset result back to links without
   duplicating it in network totals.

7. Keep auditable output fields:
   physical_asset_id, model_id, length_km, bores, lanes_per_bore,
   span_or_diameter_m, geometry_basis, cost_2008_usd,
   escalation_factor, target_price_year, construction_value_usd,
   damage_ratio, direct_damage_usd, assumption_flags.

   Flag missing/nonpositive geometry, invalid bore counts, negative
   model predictions and missing damage inputs; never replace them
   with zero costs.

8. Add the source near the top of the script:
   Rostami et al. (2013), Tunnelling and Underground Space Technology
   33:22–33, Table 9. DOI: 10.1016/j.tust.2012.08.002.
   The equations estimate construction/bid contract cost, not complete
   program cost. Design, construction management, financing and legal
   costs are excluded; contract scope varies.

Validate one highway example:
   L=1 km, lanes=2, bores=1, default geometry
   D=10.7536 m
   cost ≈ $78.67 million in December 2008 USD.