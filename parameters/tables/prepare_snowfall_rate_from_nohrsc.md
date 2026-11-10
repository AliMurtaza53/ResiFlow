# Script spec: derive snowfall rate from NOHRSC grids (CORRECTED v2)

## Corrections from v1 (per Claude Code's review)
1. **Product code was wrong.** "1034" is snow water equivalent (SWE), not depth.
   Depth is product 1036. This matters doubly now: depth (1036) is NOT what
   should feed T19-ALT's rate table -- SWE (product 1034, the one v1 mislabeled)
   is the correct liquid-equivalent input. The script should difference the
   **SWE** grids for T19-ALT's rate/intensity classification, and can keep the
   depth (1036) differencing as a separate diagnostic if useful elsewhere, but
   the two must not be used interchangeably for HCM/SHRP2-L08 bin lookups.
2. **Jonas's path is `snodas_jan2016/`, not `snodas_3day/`.** The script must
   map this explicitly per-event rather than assuming one folder name for all
   four; the existing implementation already does this correctly per Claude
   Code's report -- confirm this mapping is preserved in any rewrite.

## What this does
Converts SNODAS SWE (snow water equivalent, product 1034) snapshots already
on disk, or newly pulled, into a **liquid-equivalent accumulation rate**
(in/hr) per pixel -- this is the actual predictor variable the HCM/SHRP2-L08
and Hranac/FHWA speed/capacity WAFs were calibrated on, confirmed directly:
ASOS/AWOS station gauges (Heated Tipping Bucket, All-Weather Precipitation
Accumulation Gauge) measure liquid-equivalent accumulation only, not snow
depth. A depth-differenced rate (what v1 produced) is NOT the same quantity
as what these studies' thresholds are defined against -- typical snow is
roughly 8-12x depth per unit of liquid equivalent, so depth-differenced rates
will systematically land in higher intensity bins than the liquid-equivalent
truth. This is confirmed empirically in Claude Code's v1 run: the depth-gain-
per-SWE-gain ratio came out to 7.5-8.4 across the four events, consistent
with the standard ~10:1 snow-to-liquid approximation.

**Practical implication**: the `snowfall_rate_swe_in_hr` column Claude Code
already added as an unrequested diagnostic in v1 is in fact the CORRECT input
column for T19-ALT's bin lookup. Use that column, not the depth-differenced
`snowfall_rate_in_hr`, for the HCM/SHRP2-L08 comparison. Keep both columns in
output -- the depth-based one may still be useful for other purposes (e.g.
correlating with T19's primary depth-proxy crosswalk, since that one IS
depth-based and internally consistent with itself).

## Why
T19's depth-proxy crosswalk is a proxy precisely because no study uses
accumulated ground depth as its predictor. This script produces the real
predictor from data already in hand, letting you apply the HCM/Hranac
coefficients directly rather than through a crosswalk.

## Data already on disk
Each event has 3 daily SNODAS tars under `snodas_3day/`:
- day before peak
- peak day
- day after peak

These are daily (24h) snapshots. Differencing consecutive days gives a 24h-average
accumulation rate -- coarser than ideal (ASOS stations used by Hranac report hourly)
but still a direct rate measurement, not a proxy.

## Better option: pull 6-hourly grids
NOHRSC publishes the same SNODAS product at 6-hourly intervals (same archive,
different product code). If pulled for the same 3-day windows:
- 12 snapshots per event (vs. 3 daily)
- differencing gives 6-hourly accumulation increments
- divide by 6 -> mm/hr rate at 1km resolution
- temporal resolution comparable to ASOS hourly data the studies used

## Script logic (pseudocode)
```python
for each event in [jonas, uri, elliott, snowmageddon]:
    grids = load_chronological_snodas_grids(event)  # 3 daily or 12 6-hourly
    for i in range(1, len(grids)):
        delta = grids[i] - grids[i-1]            # mm depth change
        delta = np.clip(delta, 0, None)           # ignore negative (melt/settle)
        hours = time_diff_hours(grids[i], grids[i-1])  # 24 or 6
        rate_mm_hr = delta / hours
        rate_in_hr = rate_mm_hr / 25.4
    peak_rate = max across all intervals           # or mean during accumulation periods
    # Bin into HCM snow intensity categories:
    # light:        0.00 - 0.05 in/hr  (0.0 - 1.27 mm/hr)
    # light-medium: 0.05 - 0.10 in/hr  (1.27 - 2.54 mm/hr)
    # medium-heavy: 0.10 - 0.50 in/hr  (2.54 - 12.7 mm/hr)
    # heavy:        > 0.50 in/hr       (> 12.7 mm/hr)
```

## Output
Per-link `snowfall_rate_in_hr` column (spatial max or mean over link geometry,
same as existing `winter_storm_max_mm` spatial aggregation), plus a categorical
`hcm_snow_intensity_bin` (light/light-medium/medium-heavy/heavy).

These feed directly into T19-ALT's Table 1 (HCM CAFs/SAFs by intensity bin)
for a rate-based speed/capacity estimate that runs alongside T19's depth-based
estimate, giving two independent estimates per link per event.

## Download source for 6-hourly grids (if daily differencing is too coarse)
NOHRSC SNODAS archive: https://nsidc.org/data/g02158
Product: 1034 (Snow Depth) at 6-hourly temporal resolution
Same spatial resolution (1km) and format (.tar/.grz) as the daily product
already being pulled by prepare_snodas_depth.py.
