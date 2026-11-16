#!/usr/bin/env python3
"""Commute vehicle occupancy and mode shares from ACS B08301, county scale.

Replaces, for the ResiFlow passenger module:
  * 1.52 (NHTS all-purpose occupancy)           -> commute_avo
  * 2.4 "standard planning estimate" carpool    -> computed from B08301 size bins
  * 0.73 persons->vehicles factor               -> vehicles_per_all_worker (apply to LODES JOBS; see note)
  * 69.2% / 9.2% blog-sourced shares            -> shares of commuting workers
  * 1.06 / 1.1 legacy UK fallbacks              -> removed (no fallback)

Why conditioning on commuters matters: LODES counts jobs, and ACS B08301 shares are
of ALL workers, including those who work from home (B08301_021). Home workers make no
trip on the network, so they are removed from the denominator.

Usage (live API, run on a machine with internet):
  python commute_occupancy.py --counties 06059 51059 --year 2024 --survey acs5 \
      --outdir out
Offline (saved API responses, one JSON file per call, e.g. saved from a browser):
  python commute_occupancy.py --json resp_06059.json --year 2024 --survey acs5 --outdir out
A Census API key is optional for light use: --key YOURKEY or env CENSUS_API_KEY.
"""
import argparse, json, os, sys, urllib.request, urllib.parse
from datetime import date

# B08301 estimate variables used
VARS = {
    "total": "B08301_001E",
    "car_total": "B08301_002E",
    "drove_alone": "B08301_003E",
    "carpool_total": "B08301_004E",
    "cp2": "B08301_005E",
    "cp3": "B08301_006E",
    "cp4": "B08301_007E",
    "cp5_6": "B08301_008E",
    "cp7p": "B08301_009E",
    "transit": "B08301_010E",
    "bicycle": "B08301_018E",
    "walked": "B08301_019E",
    "other": "B08301_020E",
    "wfh": "B08301_021E",
}
# Representative persons per vehicle in each carpool bin. The 5-6 bin uses its
# midpoint; the open-ended 7+ bin uses its lower bound (conservative, tiny weight).
BIN_SIZE = {"cp2": 2.0, "cp3": 3.0, "cp4": 4.0, "cp5_6": 5.5, "cp7p": 7.0}

SENS_LOW = 1.00        # every commuter alone
SENS_HIGH_NHTS = 1.18  # NHTS commute-only figure quoted in the parameter note (UNVERIFIED here)


def fetch(fips, year, survey, key):
    st, co = fips[:2], fips[2:]
    q = {"get": "NAME," + ",".join(VARS.values()), "for": f"county:{co}", "in": f"state:{st}"}
    if key:
        q["key"] = key
    url = f"https://api.census.gov/data/{year}/acs/{survey}?" + urllib.parse.urlencode(q, safe=",:")
    with urllib.request.urlopen(url, timeout=60) as r:
        return json.load(r), url


def fetch_all(year, survey, key):
    """All US counties in ONE call (ACS5 publishes every county; ACS1 only those over 65,000)."""
    q = {"get": "NAME," + ",".join(VARS.values()), "for": "county:*", "in": "state:*"}
    if key:
        q["key"] = key
    url = f"https://api.census.gov/data/{year}/acs/{survey}?" + urllib.parse.urlencode(q, safe=",:*")
    with urllib.request.urlopen(url, timeout=120) as r:
        return json.load(r), url


def parse(resp, skip_suppressed=False, skipped=None):
    """Census API returns [header_row, data_row, ...]."""
    hdr, rows = resp[0], resp[1:]
    out = []
    for row in rows:
        d = dict(zip(hdr, row))
        rec = {"name": d["NAME"], "fips": d["state"] + d["county"]}
        bad = False
        for k, v in VARS.items():
            x = d[v]
            if x is None or int(x) < 0:   # Census uses negative sentinels for suppressed
                if not skip_suppressed:
                    raise ValueError(f"{rec['name']}: {v} is suppressed/missing ({x})")
                bad = True
                break
            rec[k] = int(x)
        if bad:
            if skipped is not None:
                skipped.append(rec["fips"])
            continue
        out.append(rec)
    return out


def compute(r):
    carpool_sum = sum(r[k] for k in BIN_SIZE)
    if carpool_sum != r["carpool_total"]:
        raise ValueError(f"{r['name']}: carpool bins {carpool_sum} != B08301_004E {r['carpool_total']}")
    commuters = r["total"] - r["wfh"]
    auto_persons = r["drove_alone"] + carpool_sum
    vehicles = r["drove_alone"] + sum(r[k] / s for k, s in BIN_SIZE.items())
    avo = auto_persons / vehicles
    return {
        **r,
        "commuting_workers": commuters,
        "auto_persons": auto_persons,
        "auto_vehicles": vehicles,
        "commute_avo": avo,
        "avg_carpool_size": carpool_sum / sum(r[k] / s for k, s in BIN_SIZE.items()) if carpool_sum else None,
        # shares of commuting workers (WFH removed)
        "share_drive_alone": r["drove_alone"] / commuters,
        "share_carpool": carpool_sum / commuters,
        "share_transit": r["transit"] / commuters,
        "share_active_other": (r["walked"] + r["bicycle"] + r["other"]) / commuters,
        "vehicles_per_commuting_worker": vehicles / commuters,
        # share of ALL workers, for comparison with the old 69.2/9.2/0.73 logic
        "wfh_share_all_workers": r["wfh"] / r["total"],
        "vehicles_per_all_worker_legacy_basis": vehicles / r["total"],
    }


def write_outputs(results, outdir, meta, synthetic):
    os.makedirs(outdir, exist_ok=True)
    tag = "SYNTHETIC_TEST_" if synthetic else ""
    params = {
        "_meta": meta,
        "counties": {
            c["fips"]: {
                "name": c["name"],
                "commute_avo": round(c["commute_avo"], 4),
                "vehicles_per_commuting_worker": round(c["vehicles_per_commuting_worker"], 4),
                "share_drive_alone": round(c["share_drive_alone"], 4),
                "share_carpool": round(c["share_carpool"], 4),
                "share_transit": round(c["share_transit"], 4),
                "share_active_other": round(c["share_active_other"], 4),
                "avg_carpool_size": None if c["avg_carpool_size"] is None else round(c["avg_carpool_size"], 3),
                "vehicles_per_all_worker": round(c["vehicles_per_all_worker_legacy_basis"], 4),
                "avo_sensitivity_range": [SENS_LOW, SENS_HIGH_NHTS],
            } for c in results
        },
    }
    jp = os.path.join(outdir, f"{tag}commute_params.json")
    json.dump(params, open(jp, "w"), indent=2)

    L = []
    if synthetic:
        L += ["> **SYNTHETIC TEST DATA. These numbers are NOT Census data and must not be used in the model.**", ""]
    L += [f"# ResiFlow passenger occupancy parameters (commute-only)", "",
          f"Generated {meta['generated']} from ACS {meta['year']} {meta['survey']} table B08301.", "",
          "## Method",
          "- Persons in autos = drove alone + all carpool bins (B08301_003, _005 to _009).",
          "- Vehicles = drove alone + sum over bins (carpoolers / bin size). Bin sizes: 2, 3, 4, 5.5 (5-6), 7 (7+, lower bound).",
          "- `commute_avo` = persons / vehicles. Used for passenger time cost per car (persons x value of time per hour).",
          "- Commuting workers = total workers (B08301_001) minus worked from home (B08301_021). LODES counts jobs, "
          "so home workers are removed before computing shares and vehicles per worker.",
          "- `vehicles_per_commuting_worker` converts LODES commuter flows to car trips. It replaces the old 0.73.",
          "- Check enforced: carpool bins must sum to B08301_004E.", "",
          "## Final numbers by county", "",
          "| County | FIPS | commute_avo | veh/commuting worker | drive alone | carpool | transit | walk/bike/other | avg carpool size | WFH (all workers) |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for c in results:
        L.append(f"| {c['name']} | {c['fips']} | {c['commute_avo']:.3f} | {c['vehicles_per_commuting_worker']:.3f} | "
                 f"{c['share_drive_alone']:.1%} | {c['share_carpool']:.1%} | {c['share_transit']:.1%} | "
                 f"{c['share_active_other']:.1%} | {'' if c['avg_carpool_size'] is None else format(c['avg_carpool_size'], '.2f')} | {c['wfh_share_all_workers']:.1%} |")
    L += ["", "## Raw B08301 counts", "",
          "| FIPS | total | WFH | drove alone | carpool | 2p | 3p | 4p | 5-6p | 7+p | transit | walked | bicycle | other |",
          "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for c in results:
        L.append(f"| {c['fips']} | {c['total']:,} | {c['wfh']:,} | {c['drove_alone']:,} | {c['carpool_total']:,} | "
                 f"{c['cp2']:,} | {c['cp3']:,} | {c['cp4']:,} | {c['cp5_6']:,} | {c['cp7p']:,} | {c['transit']:,} | "
                 f"{c['walked']:,} | {c['bicycle']:,} | {c['other']:,} |")
    L += ["", "## Sensitivity and caveats",
          f"- Run `commute_avo` over [{SENS_LOW}, {SENS_HIGH_NHTS}]. The 1.18 upper value is the NHTS commute-only figure from the "
          "old parameter note and has not been verified against the NHTS tables.",
          "- ACS carpool counts only workers sharing a ride, so it omits non-worker passengers (kids, etc.). The ACS-derived "
          "AVO is therefore a lower bound relative to NHTS-style person counts.",
          "- ACS reports usual mode last week, not mode for every trip. Estimates carry sampling error (ACS MOE variables "
          "B08301_xxxM are not pulled here).",
          "- Retired: 1.52 (all-purpose), 2.4 (uncited), 0.73 (all-worker basis), 69.2%/9.2% (blog), 1.06/1.1 (UK fallbacks).",
          "- Freight must not use any of these. Give trucks their own driver occupancy and value of time per truck-hour.",
          f"- Source URL pattern: https://api.census.gov/data/{meta['year']}/acs/{meta['survey']}?get=NAME,B08301_001E,...&for=county:CCC&in=state:SS"]
    mp = os.path.join(outdir, f"{tag}commute_params.md")
    open(mp, "w").write("\n".join(L) + "\n")
    return jp, mp


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--counties", nargs="*", default=[], help="5-digit state+county FIPS, e.g. 06059 51059")
    ap.add_argument("--all-counties", action="store_true", help="fetch every US county in one call (needs --key)")
    ap.add_argument("--csv", help="also write a flat per-county CSV here")
    ap.add_argument("--json", nargs="*", default=[], help="saved Census API response files (offline mode)")
    ap.add_argument("--year", type=int, default=2024)
    ap.add_argument("--survey", default="acs5", choices=["acs1", "acs5"])
    ap.add_argument("--key", default=os.environ.get("CENSUS_API_KEY"))
    ap.add_argument("--outdir", default="out")
    ap.add_argument("--synthetic", action="store_true", help="mark outputs as synthetic test data")
    a = ap.parse_args()

    recs, urls, skipped = [], [], []
    if a.all_counties:
        resp, url = fetch_all(a.year, a.survey, a.key)
        recs += parse(resp, skip_suppressed=True, skipped=skipped); urls.append(url)
        if skipped:
            print(f"skipped {len(skipped)} counties with suppressed B08301 cells: {skipped[:10]}...", file=sys.stderr)
    for f in a.counties:
        resp, url = fetch(f, a.year, a.survey, a.key)
        recs += parse(resp); urls.append(url)
    for p in a.json:
        recs += parse(json.load(open(p)))
        urls.append(f"file:{p}")
    if not recs:
        sys.exit("No input. Pass --counties or --json.")
    results = [compute(r) for r in recs]
    meta = {"generated": str(date.today()), "year": a.year, "survey": a.survey, "sources": urls}
    jp, mp = write_outputs(results, a.outdir, meta, a.synthetic)
    if a.csv:
        import csv
        cols = ["fips", "name", "commute_avo", "vehicles_per_commuting_worker", "vehicles_per_all_worker_legacy_basis",
                "wfh_share_all_workers", "share_drive_alone", "share_carpool", "share_transit", "share_active_other"]
        with open(a.csv, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh); w.writerow(cols)
            for c in results:
                w.writerow([c[k] for k in cols])
    if len(results) > 50:
        print(f"{len(results)} counties; table omitted. wrote", jp, mp)
        return
    print(open(mp).read())
    print("wrote", jp, mp)


if __name__ == "__main__":
    main()
