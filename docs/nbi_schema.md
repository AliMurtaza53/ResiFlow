# National Bridge Inventory (NBI) Field Data Dictionary

This document defines the field names, descriptions, data types, and common
code values for raw National Bridge Inventory (NBI) records, based on the
FHWA "Recording and Coding Guide for the Structure Inventory and Appraisal of
the Nation's Bridges" (data dictionary DOI:
[10.21949/1519105](https://doi.org/10.21949/1519105)). The full guide is
saved locally at
[`docs/reference/nbi_recording_and_coding_guide.pdf`](reference/nbi_recording_and_coding_guide.pdf)
— every code table below was checked directly against that PDF (page numbers
cited per row/section), not reconstructed from memory. An earlier version of
this file guessed several code tables from memory and got them wrong (most
seriously `SERVICE_LEVEL_005C`, where it had swapped codes 2/3/4/6 and
invented a "4=Ramp" that doesn't exist — the real ramp code is 7); see
`scripts/download_nbi_bridges.py`'s own comments for that history. Treat any
future addition to this file the same way: check the PDF before writing a
label down.

---

## 1. Structure & Location Identification

| Field Name | Description | Type / Format | Example Value | Coding Notes |
| :--- | :--- | :--- | :--- | :--- |
| `STATE_CODE_001` | FIPS State Code | String (2) | `51` | `51` = Virginia (standard FIPS state code, not defined by the NBI guide itself) |
| `STRUCTURE_NUMBER_008` | Unique Structure ID | String (15) | `0080000000000111` | Unique ID assigned by state DOT (Item 8, p.17) |
| `RECORD_TYPE_005A` | Record Type | String (1) | `1` | `1` = inventory route "on" the structure; `2` (or `A`-`Z` for multiple "under" routes) = inventory route "under" the structure (Item 5A, p.13-14) |
| `ROUTE_PREFIX_005B` | Route Signing Prefix | String (1) | `2` | `1`=Interstate highway, `2`=U.S. numbered highway, `3`=State highway, `4`=County highway, `5`=City street, `6`=Federal lands road, `7`=State lands road, `8`=Other (incl. toll roads not otherwise identified) (Item 5B, p.14) |
| `SERVICE_LEVEL_005C` | Designated Level of Service | String (1) | `1` | `0`=None of the below, `1`=Mainline, `2`=Alternate, `3`=Bypass, `4`=Spur, `6`=Business, `7`=Ramp, Wye, Connector, etc., `8`=Service and/or unclassified frontage road (Item 5C, p.14) |
| `ROUTE_NUMBER_005D` | Route Number | String (5) | `00015` | 5-digit padded route number (e.g., US-15) |
| `HIGHWAY_DISTRICT_002` | State Highway District | String (2) | `09` | State-assigned, not defined by the NBI guide; `09` = Northern Virginia (VDOT District 9) specifically for Virginia records |
| `COUNTY_CODE_003` | FIPS County Code | String (3) | `107` | Standard FIPS county code; `107` = Loudoun County, VA |
| `PLACE_CODE_004` | FIPS Place Code | String (5) | `07250` | Standard FIPS place code; `07250` = Town of Leesburg, VA |
| `FEATURES_DESC_006A` | Feature Intersected | String (24) | `DRY RUN` | Feature crossed (stream, road, rail, etc.) (Item 6A, p.16) |
| `FACILITY_CARRIED_007` | Facility Carried | String (18) | `JAMES MONROE NBL` | Roadway name supported by bridge (Item 7, p.16) |
| `LOCATION_009` | Narrative Location | String (25) | `00.14FR644/01.75TO773` | Distance from landmark/intersection (Item 9, p.17) |
| `LAT_016` | Latitude (Raw NBI) | String (8) | `39081434` | Degrees, Minutes, Seconds (`DDMMSSss`) (Item 16, p.19-20) |
| `LONG_017` | Longitude (Raw NBI) | String (9) | `077325103` | Degrees, Minutes, Seconds (`DDDMMSSss`) (Item 17, p.20) |
| `LATDD` | Latitude (Decimal) | Float | `39.1375` | NTAD-provided decoded WGS84 latitude (not a raw NBI item; see `scripts/load_ntad_bridge_gdb.py`) |
| `LONGDD` | Longitude (Decimal) | Float | `-77.548283` | NTAD-provided decoded WGS84 longitude (not a raw NBI item) |

---

## 2. Classification & Ownership

| Field Name | Description | Type / Format | Code Values & Meaning |
| :--- | :--- | :--- | :--- |
| `MAINTENANCE_021` | Maintenance Responsibility | String (2) | Item 21, p.23. Selected codes: `01`=State Highway Agency, `02`=County Highway Agency, `03`=Town or Township Highway Agency, `04`=City or Municipal Highway Agency, `11`=State Park/Forest/Reservation Agency, `12`=Local Park/Forest/Reservation Agency, `21`=Other State Agencies, `25`=Other Local Agencies, `26`=Private (other than railroad), `27`=Railroad, `31`=State Toll Authority, `32`=Local Toll Authority, `60`=Other Federal Agencies, `61`=Indian Tribal Government, `62`=Bureau of Indian Affairs, `70`=Corps of Engineers (Civil), `71`=Corps of Engineers (Military), `80`=Unknown. Full list of ~28 codes in the guide (p.23). |
| `OWNER_022` | Owner Agency | String (2) | Item 22, p.23 — uses the identical code table as `MAINTENANCE_021` above (the guide explicitly says so; it does not repeat the table). |
| `FUNCTIONAL_CLASS_026` | Functional Classification of Inventory Route | String (2) | Item 26, p.24. Rural: `01`=Principal Arterial-Interstate, `02`=Principal Arterial-Other, `06`=Minor Arterial, `07`=Major Collector, `08`=Minor Collector, `09`=Local. Urban: `11`=Principal Arterial-Interstate, `12`=Principal Arterial-Other Freeway/Expressway, `14`=Other Principal Arterial, `16`=Minor Arterial, `17`=Collector, `19`=Local. |
| `YEAR_BUILT_027` | Year Built | Integer (4) | Year constructed (e.g., `1966`, `2008`) (Item 27, p.24) |
| `YEAR_RECONSTRUCTED_106` | Year Reconstructed | Integer (4) | Year of most recent reconstruction; `0000` if none (Item 106, p.68) |
| `HIGHWAY_SYSTEM_104` | NHS Status | String (1) | `0` = Inventory route not on the NHS; `1` = Inventory route is on the National Highway System (Item 104, p.68) |
| `STRAHNET_HIGHWAY_100` | STRAHNET Highway Designation | String (1) | `0`=Not a STRAHNET route, `1`=Interstate STRAHNET route, `2`=Non-Interstate STRAHNET route, `3`=STRAHNET connector route (Item 100, p.67) |

---

## 3. Physical Geometry & Structure Type

| Field Name | Description | Type / Format | Notes & Conversions |
| :--- | :--- | :--- | :--- |
| `STRUCTURE_KIND_043A` | Main Kind of Material/Design | String (1) | Item 43A, p.35: `1`=Concrete, `2`=Concrete continuous, `3`=Steel, `4`=Steel continuous, `5`=Prestressed concrete, `6`=Prestressed concrete continuous, `7`=Wood or Timber, `8`=Masonry, `9`=Aluminum/Wrought Iron/Cast Iron, `0`=Other |
| `STRUCTURE_TYPE_043B` | Main Type of Design/Construction | String (2) | Item 43B, p.36: `01`=Slab, `02`=Stringer/Multi-beam or Girder, `03`=Girder and Floorbeam System, `04`=Tee Beam, `05`=Box Beam/Girders-Multiple, `06`=Box Beam/Girders-Single or Spread, `07`=Frame, `08`=Orthotropic, `09`=Truss-Deck, `10`=Truss-Thru, `11`=Arch-Deck, `12`=Arch-Thru, `13`=Suspension, `14`=Stayed Girder, `15`=Movable-Lift, `16`=Movable-Bascule, `17`=Movable-Swing, `18`=Tunnel, `19`=Culvert (incl. frame culverts), `21`=Segmental Box Girder, `22`=Channel Beam, `00`=Other. (No "exotic/cable" category exists — an earlier version of this doc invented that label for code 22, which is actually Channel Beam.) |
| `MAIN_UNIT_SPANS_045` | Main Spans Count | Integer | Number of spans in the main/major unit (Item 45, p.37) |
| `STRUCTURE_LEN_MT_049` | Total Length (m) | Float | Overall length in meters, back-to-back of abutment backwalls (Item 49, p.39). Multiply by `3.28084` for feet. |
| `MAX_SPAN_LEN_MT_048` | Max Span Length (m) | Float | Length of maximum single span in meters (Item 48, p.38) |
| `DECK_WIDTH_MT_052` | Out-to-Out Deck Width (m) | Float | Total out-to-out width of bridge deck (Item 52, p.44). `0.0` is used for "not applicable"/fill-covered culverts and is NBI's "not recorded" convention in practice — see `_clean_deck_width()` in `scripts/download_nbi_bridges.py`, which treats it as missing rather than a real zero-width bridge (14.3% of national records carry exactly 0). |
| `ROADWAY_WIDTH_MT_051` | Curb-to-Curb Width (m) | Float | Usable roadway width on deck, most restrictive minimum (Item 51, p.43) |
| `DECK_AREA` | Deck Area (m²) | Float | Derived field provided by the NTAD distribution, not an official numbered NBI item — approximately `structure_length_m x deck_width_m`. |
| `VERT_CLR_UND_054B` | Under-clearance (m) | Float | Minimum vertical clearance under structure (Item 54B, p.44-45) |
| `DEGREES_SKEW_034` | Skew Angle | Integer | Skew angle in degrees relative to perpendicular; `99` indicates major variation across substructure units (Item 34, p.30) |

---

## 4. Traffic & Operational Parameters

| Field Name | Description | Type / Format | Operational Impact |
| :--- | :--- | :--- | :--- |
| `TRAFFIC_LANES_ON_028A` | Lanes On Structure | Integer | Number of traffic lanes carried (Item 28A, p.25) |
| `TRAFFIC_LANES_UND_028B` | Lanes Under Structure | Integer | Number of traffic lanes passing beneath (Item 28B, p.25) |
| `TRAFFIC_DIRECTION_102` | Direction of Traffic | String (1) | `0`=Highway traffic not carried, `1`=1-way traffic, `2`=2-way traffic, `3`=One lane bridge for 2-way traffic (Item 102, p.68) |
| `ADT_029` | Average Daily Traffic | Integer | Annual Average Daily Traffic (AADT) volume, including trucks (Item 29, p.26) |
| `YEAR_ADT_030` | Year of ADT Record | Integer | Year AADT was recorded (e.g., `2022`) (Item 30, p.27) |
| `PERCENT_ADT_TRUCK_109` | Truck Traffic (%) | Integer | Percentage of AADT consisting of heavy trucks (Item 109) |
| `FUTURE_ADT_114` | Future Projected ADT | Integer | Forecasted AADT volume (Item 114) |
| `YEAR_OF_FUTURE_ADT_115` | Year of Future ADT | Integer | Forecast target year (e.g., `2042`) (Item 115) |
| `DETOUR_KILOS_019` | Detour Length (km) | Integer | Bypass detour distance if bridge is closed; `199` means 199km or more (Item 19, p.21) |

---

## 5. Condition Ratings & Inspections

> **NBI Condition Scale (Items 58-62, p.38-40):**
> `9` = Excellent; `8` = Very Good (no problems noted); `7` = Good (some minor
> problems); `6` = Satisfactory (minor deterioration); `5` = Fair (sound, but
> minor section loss/cracking/spalling/scour); `4` = Poor (advanced section
> loss/deterioration/spalling/scour); `3` = Serious (loss of section has
> seriously affected primary structural components; local failures
> possible); `2` = Critical (advanced deterioration; may require closure
> unless closely monitored); `1` = Imminent Failure (bridge closed to
> traffic); `0` = Failed (out of service); `N` = Not Applicable.

| Field Name | Description | Rating Scope |
| :--- | :--- | :--- |
| `DECK_COND_058` | Deck Rating | Overall condition of the deck (`N` for culverts and decks without a deck, e.g. filled arch bridges) (Item 58, p.38) |
| `SUPERSTRUCTURE_COND_059` | Superstructure Rating | Condition of all structural members (`N` for all culverts) (Item 59, p.39) |
| `SUBSTRUCTURE_COND_060` | Substructure Rating | Condition of piers, abutments, piles, footings (`N` for all culverts) (Item 60, p.39) |
| `CULVERT_COND_062` | Culvert Rating | Condition of the culvert barrel/structure (`N` for non-culvert bridges) (Item 62) |
| `CHANNEL_COND_061` | Channel/Bank Rating | Stream bed erosion, riprap, and bank stability (Item 61) |
| `SCOUR_CRITICAL_113` | Scour Vulnerability | Item 113, p.75-76. `N`=not over waterway, `U`=unknown foundation, not evaluated, `T`=tidal waters, not evaluated but low risk, `9`=foundations on dry land above flood elevations, `8`=stable, calculated scour above top of footing, `7`=countermeasures installed, no longer critical, `6`=not yet evaluated, `5`=stable, scour within limits of footing/piles, `4`=stable but action required to protect exposed foundations, `3`=scour critical (unstable), `2`=scour critical, extensive scour observed, `1`=scour critical, failure imminent, closed, `0`=scour critical, bridge has failed and is closed. |
| `BRIDGE_CONDITION` | NBI Categorical Condition | FHWA-computed summary field, not a raw numbered item: **`G`** = Good (lowest applicable of Items 58/59/60/62 ≥ 7); **`F`** = Fair (lowest = 5-6); **`P`** = Poor (lowest ≤ 4) |
| `LOWEST_RATING` | Minimum Condition Score | Derived: min(applicable ratings among Items 58, 59, 60, 62) |
| `DATE_OF_INSPECT_090` | Last Inspection Date | `MMYY` format (e.g., `0724` = July 2024) (Item 90, p.62) |
| `INSPECT_FREQ_MONTHS_091`| Inspection Cycle | Interval in months between designated inspections; standard = `24` (Item 91, p.62) |

---

## 6. Structural Load Evaluation & Improvements

| Field Name | Description | Type / Format | Meaning |
| :--- | :--- | :--- | :--- |
| `OPR_RATING_METH_063` | Method Used to Determine Operating Rating | String (1) | `1`=Load Factor (LF), `2`=Allowable Stress (AS), `3`=Load and Resistance Factor (LRFR), `4`=Load Testing, `5`=No rating analysis performed (Item 63, p.42) |
| `OPERATING_RATING_064` | Operating Rating | Float | Maximum allowable gross vehicle weight, metric tons; `999` = under sufficient fill that live load is insignificant (Item 64, p.43) |
| `INV_RATING_METH_065` | Method Used to Determine Inventory Rating | String (1) | Same code table as `OPR_RATING_METH_063` above (Item 65, p.43) |
| `INVENTORY_RATING_066` | Inventory Rating | Float | Capacity for indefinite normal traffic, metric tons (Item 66, p.43) |
| `OPEN_CLOSED_POSTED_041`| Structure Open, Posted, or Closed to Traffic | String (1) | Item 41, p.33-34: `A`=Open, no restriction; `B`=Open, posting recommended but not implemented; `D`=Open, would be posted/closed except for temporary shoring; `E`=Open, temporary structure carrying legal loads while original is closed for replacement/rehab (not "emergency vehicles only" — an earlier version of this doc had that wrong); `G`=New structure not yet open; `K`=Closed to all traffic; `P`=Posted for load; `R`=Posted for other restriction (speed, vehicle count, etc.) |
| `WORK_PROPOSED_075A` | Proposed Work Code | String (2) | Item 75A, p.58-59: `31`=Replacement (substandard capacity/geometry), `32`=Replacement (road relocation), `33`=Widening without deck rehab/replacement, `34`=Widening with deck rehab/replacement, `35`=Rehabilitation (general deterioration/inadequate strength), `36`=Deck rehab (incidental widening only), `37`=Deck replacement (incidental widening only), `38`=Other structural work. (An earlier version of this doc had 33 and 35 swapped.) |
| `TOTAL_IMP_COST_096` | Total Project Cost | Integer ($1,000s) | Total estimated project cost, thousands of dollars (Item 96, p.65) |
