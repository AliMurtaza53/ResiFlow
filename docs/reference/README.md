# Reference documents

- **`nbi_recording_and_coding_guide.pdf`** — FHWA's official "Recording and
  Coding Guide for the Structure Inventory and Appraisal of the Nation's
  Bridges" (the NBI data dictionary). Reached via the data dictionary DOI
  https://doi.org/10.21949/1519105, which resolves to
  https://www.fhwa.dot.gov/bridge/mtguide.pdf (saved here 2026-08-19).
  Authoritative source for every `*_NNN` field code used in
  `scripts/download_nbi_bridges.py` and `scripts/load_ntad_bridge_gdb.py`
  (`ROUTE_PREFIX_005B` p.14, `SERVICE_LEVEL_005C` p.14, `FUNCTIONAL_CLASS_026`
  p.24, `STRUCTURE_TYPE_043B` pp.35-36, etc.) — check here before adding or
  changing any label mapping for these fields, rather than relying on memory
  (an earlier version of this project's code guessed several of these
  mappings from memory and got at least one demonstrably wrong; see
  `download_nbi_bridges.py`'s own comments for that history).

- **`phase0_flood_summary.csv`** — pinned Sioux Falls toy-network baseline
  used by `tests/test_phase0_summary_parity.py` for regression testing.
