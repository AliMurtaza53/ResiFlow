"""Pull EMFAC2025 fuel rates for T04 seal: MDV (gas SUV) + T7 Tractor Class 8 (HT)."""
from __future__ import annotations

import csv
import statistics as stats
from collections import defaultdict
from pathlib import Path

RAW = Path(
    "parameters/tables/raw/"
    "EMFAC2025EI-EMFAC202YClass-Statewide-2026-Annual-20260911195848.csv"
)
OUT_SPEED = Path("parameters/tables/T04_EMFAC2025_CA_fuel_speed.csv")
OUT_AVG = Path("parameters/tables/T04_avg_fuel_VOC.csv")

GAS_USD_PER_GAL = 3.15  # NewT0 / EIA 2024 national avg (matches sealed T04 passenger)
DIESEL_USD_PER_GAL = 3.65
L_PER_KM_PER_GAL_PER_MI = 2.35215  # 3.78541/1.60934


def load_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8-sig") as f:
        for _ in range(8):
            next(f)
        return list(csv.DictReader(f))


def gal_per_mi(row: dict) -> float | None:
    cvmt = float(row["CVMT"])
    fuel = float(row["Fuel Consumption"])  # 1000 gal/day
    if cvmt <= 0:
        return None
    return (fuel * 1000.0) / cvmt


def series(rows, vehicle_category: str, fuel: str) -> list[tuple[int, float]]:
    out = []
    for row in rows:
        if row["Vehicle Category"] != vehicle_category:
            continue
        if row["Fuel"] != fuel:
            continue
        gpm = gal_per_mi(row)
        if gpm is None:
            continue
        out.append((int(float(row["Speed"])), gpm))
    out.sort()
    return out


def fleet_t7_class8_diesel(rows) -> list[tuple[int, float]]:
    by_speed: dict[int, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for row in rows:
        vc = row["Vehicle Category"]
        if not (vc.startswith("T7") and "Class 8" in vc):
            continue
        if row["Fuel"] != "Diesel":
            continue
        sp = int(float(row["Speed"]))
        by_speed[sp][0] += float(row["CVMT"])
        by_speed[sp][1] += float(row["Fuel Consumption"])
    out = []
    for sp in sorted(by_speed):
        cvmt, fuel = by_speed[sp]
        if cvmt <= 0:
            continue
        out.append((sp, (fuel * 1000.0) / cvmt))
    return out


def mean_gpm(series_: list[tuple[int, float]], lo: int = 5, hi: int = 80) -> float:
    """Equal-weight mean over speed bins in [lo, hi] mph (Li-style constant)."""
    vals = [g for s, g in series_ if lo <= s <= hi]
    if not vals:
        raise ValueError(f"no speed bins in [{lo}, {hi}] for mean")
    return stats.mean(vals)


def main():
    rows = load_rows(RAW)
    mdv = series(rows, "MDV", "Gasoline")
    t6 = series(rows, "T6 Instate Delivery Class 6", "Diesel")
    t7 = series(rows, "T7 Tractor Class 8", "Diesel")
    t7_fleet = fleet_t7_class8_diesel(rows)

    print("MDV Gasoline bins 5-80", sum(1 for s, _ in mdv if 5 <= s <= 80), "mean gal/mi", round(mean_gpm(mdv), 4))
    print("T6 SU Class6 Diesel 5-80", sum(1 for s, _ in t6 if 5 <= s <= 80), "mean", round(mean_gpm(t6), 4))
    print("T7 Tractor Class8 Diesel 5-80", sum(1 for s, _ in t7 if 5 <= s <= 80), "mean", round(mean_gpm(t7), 4))
    print(
        "T7 Class8 fleet Diesel 5-80",
        sum(1 for s, _ in t7_fleet if 5 <= s <= 80),
        "mean",
        round(mean_gpm(t7_fleet), 4),
    )

    # Speed table: MDV + T7 Tractor (sealed freight class)
    speeds = sorted({s for s, _ in mdv} | {s for s, _ in t7})
    mdv_m = dict(mdv)
    t7_m = dict(t7)
    with OUT_SPEED.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "speed_mph",
                "speed_kmh",
                "gas_suv_gal_per_mi",
                "gas_suv_L_per_km",
                "diesel_heavy_truck_gal_per_mi",
                "diesel_heavy_truck_L_per_km",
            ]
        )
        for sp in speeds:
            kmh = round(sp * 1.60934, 1)
            g_suv = mdv_m.get(sp)
            g_ht = t7_m.get(sp)
            w.writerow(
                [
                    sp,
                    kmh,
                    "" if g_suv is None else round(g_suv, 4),
                    "" if g_suv is None else round(g_suv * L_PER_KM_PER_GAL_PER_MI, 4),
                    "" if g_ht is None else round(g_ht, 4),
                    "" if g_ht is None else round(g_ht * L_PER_KM_PER_GAL_PER_MI, 4),
                ]
            )
        # footer comments
        w.writerow([])
        for line in [
            "# SOURCE: EMFAC2025 v2.1.1 (CARB), Statewide CA, CY2026, Annual, avg-speed bins.",
            f"# Raw: {RAW.name}",
            '# VEHICLE MAPPING: gas_suv = EMFAC "MDV" (8,501-14,000 lb GVWR), Gasoline.',
            '#                  diesel_heavy_truck = EMFAC "T7 Tractor Class 8" '
            "(combination tractor, Class 8), Diesel.",
            "# RATIONALE: ResiFlow FAF freight / T29 / NewT0 HT are combination-unit "
            "(5+ axle), not single-unit Class 6. Replaces prior diesel_su_truck "
            '(T6 Instate Delivery Class 6).',
            "# CALC: gal/mi = Fuel Consumption (1000 gal/day) * 1000 / CVMT (mi/day).",
            f"#       L/km = gal/mi * {L_PER_KM_PER_GAL_PER_MI}.",
            "# CAVEATS: CA fleet (CARB standards); EMFAC2025 not EPA-approved for SIP.",
            "#          T7 Tractor Class 8 may lack some high-speed bins — blank cells "
            "left blank (do not invent).",
            f"# CROSS-CHECK mean gal/mi: T6 SU Class6 diesel={mean_gpm(t6):.4f}; "
            f"T7 Class8 fleet VMT-wtd={mean_gpm(t7_fleet):.4f}.",
        ]:
            w.writerow([line])

    avg_suv = mean_gpm(mdv)
    avg_ht = mean_gpm(t7)
    n_suv = sum(1 for s, _ in mdv if 5 <= s <= 80)
    n_ht = sum(1 for s, _ in t7 if 5 <= s <= 80)
    usd_suv = round(avg_suv * GAS_USD_PER_GAL, 4)
    usd_ht = round(avg_ht * DIESEL_USD_PER_GAL, 4)

    avg_body = "\n".join(
        [
            "# SOURCE: Methodology matched to Li et al. (2026) Stress-testing road "
            "network resilience (TRD).",
            "# Li et al. generalized cost = time + FUEL-ONLY + toll (no speed-bin table",
            "# in cost_func, no non-fuel VOC). Values below = equal-weight mean gal/mi",
            "# over EMFAC avg-speed bins 5-80 mph x EIA fuel price (Li-like constant).",
            "# UNDERLYING FUEL DATA: EMFAC2025 v2.1.1, Statewide CA, CY2026 Annual.",
            f"# Raw: {RAW.name}",
            "# Speed table: parameters/tables/T04_EMFAC2025_CA_fuel_speed.csv",
            "# VEHICLE MAPPING: gas_suv = EMFAC MDV Gasoline (passenger proxy).",
            '#                  diesel_heavy_truck = EMFAC "T7 Tractor Class 8" Diesel',
            "#                  (FAF/T29/NewT0 HT = combination 5+ axle; NOT T6 SU Class 6).",
            f"# FUEL PRICE: gasoline ${GAS_USD_PER_GAL}/gal, diesel ${DIESEL_USD_PER_GAL}/gal",
            "# (NewT0 / EIA 2024 national averages).",
            f"# MEAN gal/mi (5-80 mph): gas_suv={avg_suv:.4f} (n={n_suv}); "
            f"diesel_heavy_truck={avg_ht:.4f} (n={n_ht}).",
            f"# SUPERSEDED: diesel_su_truck (T6 Instate Delivery Class 6) mean "
            f"{mean_gpm(t6):.4f} gal/mi / ${mean_gpm(t6)*DIESEL_USD_PER_GAL:.4f}/mi --",
            "# wrong GVWR class for FAF long-haul combination freight.",
            "# SCOPE: fuel only (Li-like). Not full VOC (see T05).",
            "# STATUS: SEALED for Wave-1 Li-scope constant fuel VOC.",
            "vehicle_class,avg_fuel_usd_per_mile,fuel_price_usd_per_gal,fuel_type,"
            "emfac_category,status,for",
            f"gas_suv,{usd_suv},{GAS_USD_PER_GAL},gasoline,MDV,SEALED,passenger",
            f"diesel_heavy_truck,{usd_ht},{DIESEL_USD_PER_GAL},diesel,"
            "T7 Tractor Class 8,SEALED,freight",
        ]
    )
    # Prefer canonical path; if Excel has it locked, write _sealed sibling.
    try:
        OUT_AVG.write_text(avg_body + "\n", encoding="utf-8")
        print(f"wrote {OUT_AVG}")
    except PermissionError:
        alt = OUT_AVG.with_name("T04_avg_fuel_VOC_sealed.csv")
        alt.write_text(avg_body + "\n", encoding="utf-8")
        print(f"LOCKED {OUT_AVG}; wrote {alt} — close Excel and rename/replace")

    print(f"wrote {OUT_SPEED}")
    print(f"SEALED gas_suv ${usd_suv}/mi; diesel_heavy_truck ${usd_ht}/mi")
    print(
        f"(old diesel_su_truck would be ${round(mean_gpm(t6)*DIESEL_USD_PER_GAL, 4)}/mi)"
    )


if __name__ == "__main__":
    main()
