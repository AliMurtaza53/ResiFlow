# FAF5 → NBI/NTI bridge & tunnel join: review

Scope: `scripts/build_nbi_bridge_index.py`, `build_nti_tunnel_index.py`,
`download_nbi_bridges.py`, `load_ntad_bridge_gdb.py`, `load_ntad_tunnel_gpkg.py`,
`patch_faf5_{bridge,tunnel}_attributes.py`, `src/resiflow/preprocess/faf5_network.py`'s
`apply_bridge_index`/`apply_tunnel_index`/`derive_road_label`, and the real
local dry-run artifacts under `Desktop/data/faf5_data/network_data/enrichment/`
(not just the code — the actual join output was inspected). Written
2026-10-01. Legend: **FIX** = clear defect, **CONFIRM** = needs a decision,
**NOTE** = context.

Status today: **local enrichment network is the working FAF file** under
`Desktop/data/faf5_data/network_data/enrichment/faf5_road_links_bridge_tunnel_patched.gpq`
(rebuilt with `bridge_fraction` / inventory geometry guards). Committed
`preprocess.nbi_bridge_index_path` / `nti_tunnel_index_path` remain `null`
until Hopper/production paths are set — point those at the enrichment
indices (or re-convert with them) before treating any other `faf5_road_links.gpq`
as current.

**Locational, not span:** `road_bridge` / `road_tunnel` are presence flags from
a proximity join. They do **not** mean the full FAF edge length is bridge or
tunnel. Costing uses NBI/NTI inventory lengths; `bridge_fraction` /
`tunnel_fraction` quantify the mismatch. True geometry split of long FAF
edges is deferred.

---

## 1. Blocking: "bridge" is a whole-link label, but the structure covers a sliver of it

This is the headline finding — confirmed by running the numbers on the real
dry-run output (`faf5_road_links_bridge_tunnel_patched.gpq`, 483,599 links),
not just reading the code.

- **132,067 links (27.3% of the whole network) are flagged `road_label='bridge'`.**
- Those links hold **64% of total network length** — i.e. the model now
  treats most of its route-miles as bridge.
- But `bridge_fraction = structure_length_m / link length` has a **median of
  4.7%**. 68% of bridge-labeled links have the real structure covering under
  10% of the link; 23% under 1%. Only 8% of "bridge" links are actually
  mostly bridge (fraction ≥ 50%).

Why: `sjoin_nearest` finds, for each NBI point, the nearest FAF5 **link**
within 100 m — correctly (median match distance is 3.7 m, so the spatial
match itself is accurate) — but FAF5 links can be very long (mean 1,932 m,
max 1,190 km), and the *whole link* then inherits `road_label='bridge'`,
not just the stretch near the structure.

**What this does and doesn't break:**
- Direct **$ cost is already isolated correctly** — both
  `hazards/hazus_bridge.py` and `scripts/3_damage_analysis.py`'s
  `compute_damage_values` price bridges by `structure_length_m` (NBI), not
  the FAF link length, and hard-raise rather than silently fall back to link
  length. Good design, already in place.
- What's still wrong: **everything that is decided at `road_label`
  granularity instead of `structure_length_m` granularity** gets applied to
  the full link — fragility curve selection (Sa(1.0s) bridge curve vs. the
  road's no-ground-shaking rule; see `fragility/earthquake_categorical.py`,
  `landslide_categorical.py`), closures/`damage_level_max`, and (per
  `FLOOD_TABLE_REVIEW.md` item 6) T26 recovery scheduling if a bridge/road
  split is ever wired there. A 10 km arterial with one 70 m culvert now has
  its entire closure/recovery behavior decided by bridge rules, and the
  ordinary-road flood/seismic damage over the other 9.93 km is not priced as
  road damage at all (the `road_label=='road'` cost branch never runs for
  that link).
- **FIX:** tunnels already have the right instinct — `apply_tunnel_index`
  computes `tunnel_fraction = tunnel_length_m/length` precisely for this
  problem, it's just not consumed anywhere outside the length-clamp in
  `compute_damage_values`. Bridges have no equivalent `bridge_fraction` field
  at all. Two options, not mutually exclusive: (a) compute
  `bridge_fraction` the same way and gate fragility/closure logic on it
  (e.g. only use the bridge curve when `bridge_fraction` exceeds some
  threshold, else treat the link as road for fragility purposes while still
  costing the structure correctly); (b) the more correct long-term fix —
  split a matched link into a short bridge sub-segment and the remaining
  road sub-segment at ingest, so `road_label` is accurate at the geometry
  level instead of being a per-e_id flag. (a) is a small change to
  `apply_bridge_index`; (b) is a bigger network-geometry change.

## 2. Confirm: tunnel recall looks much worse than bridge recall

From `structure_coverage_compare.json`'s own cross-check against the
independent HPMS LRS-keyed subset (the only ground truth available here):
- Bridges: of 27,879 HPMS-confirmed bridge links, NBI's proximity join found
  20,774 → **~74.5% recall**.
- Tunnels: of 109 HPMS-confirmed tunnel links, NTI's proximity join found
  only 35 → **~32% recall**.

Same method (nearest-within-100m), same confidence profile reasoning should
apply, so a 2x-worse recall for tunnels is worth understanding rather than
accepting as "tunnels are just rare." Candidate causes to check: NTI publishes
**portal** coordinates (an endpoint, not a tunnel centerline or midpoint, per
`load_ntad_tunnel_gpkg.py`'s own comment), so a tunnel's portal can legitimately
sit further from the FAF5 link centerline than a bridge's own on-structure
point would — a asymmetry the bridge join doesn't have. If true, tunnels may
need either a larger `--max-distance` or a portal-to-portal (or portal
nearest-endpoint) matching strategy instead of straight nearest-link.

## 3. Fix: doc/code disagree on the tunnel conflict-resolution default

`docs/HPMS_FAF_LRS_TRANSFER.md`'s "Enrichment wiring" section says: *"patch
requires explicit `--on-conflict prefer_tunnel|prefer_bridge` (default:
error)."* The actual script, `scripts/patch_faf5_tunnel_attributes.py`,
defaults `--on-conflict` to `"prefer_tunnel"`, not `"error"` — same default
`faf5_network.convert_faf5_links()` hardcodes for a fresh conversion. No test
exercises the *default* (both `test_faf5_bridge_index.py` cases pass
`on_conflict=` explicitly), so this slipped past CI. Either the doc is stale
(likely — the code already picked a real default and runs with it) or the
default should genuinely be `error` and both call sites should change. Pick
one and make the doc and code agree.

## 4. Note: conflict resolution doesn't use match quality

164 links (0.12% of matched bridges) are flagged both bridge and tunnel. The
default resolution (`prefer_tunnel`) is a blanket rule — it doesn't compare
`match_distance_m_max` between the two candidate matches to keep whichever
one is actually closer/more confident. Low priority given the count, but
cheap to add since both indices already carry the distance field.

## 5. Note: `n_class_inconsistent` is computed but never consumed

`build_nbi_bridge_index.py` flags 10,914 of 132,231 matched links (8.3%)
where at least one matched structure's `is_ramp` disagrees with the link's
own `road_classification`. The module's own docstring calls this
"Diagnostic, not (yet) a matching change" — confirmed: grepped the whole
`src/`/`scripts/` tree, nothing downstream reads `n_class_inconsistent` or
`match_distance_m_max`. Fine as a documented, intentional gap, not a silent
one — flagging only so it isn't mistaken for a used quality filter it isn't.

## 6. Note: `structure_length_m` has no explicit "0 means not recorded" guard

`download_nbi_bridges.py`'s `_clean_deck_width()` explicitly converts NBI's
`0.0` convention for "not recorded" deck width to `NaN` (measured: 14.3% of
national records). `STRUCTURE_LEN_MT_049` → `structure_length_m` gets no
equivalent treatment (`pd.to_numeric(..., errors="coerce")` only). Empirically,
in the current real download, **0 structures have `structure_length_m` of 0
or null** (checked directly against `faf5_bridge_index.parquet`), so this
isn't biting today — but `hazus_bridge.py`'s `_bridge_asset_geometry()` and
`3_damage_analysis.py`'s `compute_damage_values` both hard-`raise` on a
missing/zero value, uncaught, inside a per-row `.apply()` over the whole
intersections table. If a future NBI refresh (or `load_ntad_bridge_gdb.py`'s
NTAD source, not yet cross-checked for this) ever has a zero/blank
`STRUCTURE_LEN_MT_049`, it will crash an entire Script 3 run for that
scenario, not just skip the one bad row. Worth either (a) confirming NTAD's
distribution never has this gap, or (b) wrapping that one `.apply()` call
with a per-row try/except that logs and drops the offending link instead of
aborting the batch.

## 7. Confirm: deck-width fallback is correct and already handles the 7.2% gap

`faf5_bridge_index.parquet` has 9,557 of 132,231 matched links (7.2%) with
null `deck_width_m` (NBI's own "not recorded" convention, correctly cleaned).
`apply_bridge_index`'s `averageWidth = overridden_width.fillna(links["averageWidth"])`
correctly falls back to the lanes-based estimate for those — confirmed 0
nulls in `averageWidth` on the final patched bridge rows. No action needed,
noted only because it's the one place the pipeline already does the
right thing for a real, measured gap, worth keeping as the model for fixing
item 1 above.

## 8. Note: `docs/nbi_schema.md` documents NBI fields only, not NTI

The user's own framing ("field dictionary only, not the join logic") already
scopes this file to NBI — but given tunnels are first-class in this pipeline
now, the NTI field names used in `load_ntad_tunnel_gpkg.py`
(`tunnel_length_g1`, `roadway_width_curb_to_curb_g3`, `service_in_tunnel_a8`,
`functional_classification_c7`, `nhs_designation_c5`) have no equivalent
dictionary anywhere in `docs/`. Low priority, but worth a short NTI
companion table if this file is meant to be the durable reference.

---

## Suggested order

1. ~~Add `bridge_fraction`~~ **Done** in `apply_bridge_index` (mirrors
   `tunnel_fraction`). Fragility/closure gating on a fraction threshold is
   still open — today the whole-link `road_label` still drives those paths.
2. ~~Resolve the `--on-conflict` doc/code mismatch~~ **Done** — doc now
   matches `prefer_tunnel` default.
3. Investigate NTI's portal-coordinate recall gap (item 2) before trusting
   tunnel coverage numbers in any report.
4. ~~Guard zero/null inventory geometry~~ **Done** at apply time: null or
   non-positive `structure_length_m` / `deck_width_m` / `tunnel_length_m`
   → exclude match (not flagged). Publish metrics via
   `scripts/publish_bridge_tunnel_coverage_metrics.py`.
5. Deferred: split long FAF edges into bridge/road sub-segments so
   `road_label` is geometry-true rather than locational.
