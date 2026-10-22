"""One internally consistent synthetic world for the layout figures (replaces independent random tables).

Every placeholder figure draws from the same per-event totals, so the sheets reconcile by construction:
  total(event)            = direct + cumulative 90-day indirect (rerouting + isolation, passenger + freight)
  RQ1_1 class bars        sum to direct(event); road classes exclude bridge structures (asset split first),
                          earthquake roads are $0 by design (bridges only); 'Severe' = severe + extensive
  RQ1_2(A) state bars     are the leading states' direct damage (mean with min-max damage-ratio range)
  RQ1_2(B)                = RQ2(B) state sum (states + Rest) = direct + indirect
  RQ2(A) mode bars        sum to the event's indirect cost; Toll is $0 and dropped
  RQ2(B) states           indirect cost attributed to the origin state
  RQ3(A)/(B)/(C)          disrupted freight tonnage / cargo value (tons x FAF5 $/ton); (C) states sum to (B)
Replace with model output when real runs are converged; nothing here is a result.
"""
import numpy as np
import pandas as pd
from pathlib import Path

VIZ = Path(__file__).resolve().parent.parent
EVENTS = ["Hurricane Harvey", "New Madrid Earthquake", "New Madrid Landslide", "Winter Storm Jonas"]
INDUSTRIES = ["Agriculture, fishing, forestry", "Mining", "Petroleum & coal products", "Manufactured goods",
              "Mixed freight & other"]
SEVERITIES = ["Minor", "Moderate", "Severe"]
CLASSES = ["Interstate", "Arterial", "Collector", "Local road", "Bridges"]

DIRECT = {"Hurricane Harvey": 5.00, "New Madrid Earthquake": 3.20, "New Madrid Landslide": 3.80, "Winter Storm Jonas": 1.60}
# indirect, 90-day cumulative, $B: (Operating, Time, Isolation) for Passenger and Freight (Toll is $0)
INDIRECT = {
    "Hurricane Harvey": dict(Passenger=(.09, .06, .14), Freight=(.03, .02, .17)),
    "New Madrid Earthquake": dict(Passenger=(.14, .12, .25), Freight=(.07, .17, .14)),
    "New Madrid Landslide": dict(Passenger=(.11, .08, .48), Freight=(.09, .07, .08)),
    "Winter Storm Jonas": dict(Passenger=(.44, .40, .89), Freight=(.06, .12, .10)),
}
CLASS_SHARE = {
    "Hurricane Harvey": (.22, .24, .14, .12, .28),
    "New Madrid Earthquake": (0, 0, 0, 0, 1.0),
    "New Madrid Landslide": (.26, .20, .12, .22, .20),
    "Winter Storm Jonas": (.35, .25, .15, .10, .15),
}
# state shares of damage in rank order (4 named states, then 'Rest' = remaining states)
STATES = {
    "Hurricane Harvey": (["Texas", "Louisiana", "Mississippi", "Arkansas"], [.60, .14, .09, .06, .11]),
    "New Madrid Earthquake": (["Missouri", "Tennessee", "Arkansas", "Illinois"], [.34, .26, .18, .09, .13]),
    "New Madrid Landslide": (["West Virginia", "Kentucky", "Virginia", "Tennessee"], [.38, .24, .16, .09, .13]),
    "Winter Storm Jonas": (["Virginia", "New York", "Maryland", "Pennsylvania"], [.36, .24, .16, .10, .14]),
}
# denominators (placeholders): exposed lane-miles, affected-county population, annual freight value of the affected area ($B)
LANE_MILES = {"Hurricane Harvey": 52_000, "New Madrid Earthquake": 61_000, "New Madrid Landslide": 58_000, "Winter Storm Jonas": 98_000}
POPULATION = {"Hurricane Harvey": 6.9e6, "New Madrid Earthquake": 11.0e6, "New Madrid Landslide": 9.0e6, "Winter Storm Jonas": 38.0e6}
FREIGHT_VALUE = {"Hurricane Harvey": 60.0, "New Madrid Earthquake": 45.0, "New Madrid Landslide": 38.0, "Winter Storm Jonas": 120.0}
TONS_MT = {"Hurricane Harvey": 35.2, "New Madrid Earthquake": 16.4, "New Madrid Landslide": 20.5, "Winter Storm Jonas": 18.3}
DAMAGE_BAND = 0.12  # half-width of the min-max damage-ratio range as a share of the mean


def _rng(name):
    return np.random.default_rng(sum((i + 1) * ord(c) for i, c in enumerate(name)) % (2 ** 32))


def mode_components():
    """event x mode rows with Operating, Time, Isolation ($B)."""
    rows = []
    for e in EVENTS:
        for mode, (op, tm, iso) in INDIRECT[e].items():
            rows.append(dict(hazard=e, flow=mode, Operating=op, Time=tm, Isolation=iso))
    return pd.DataFrame(rows)


def event_totals():
    """event rows: Direct, Rerouting, Isolation, freight-only Rerouting/Isolation, Total, denominators."""
    rows = []
    for e in EVENTS:
        rer = sum(op + tm for op, tm, _ in INDIRECT[e].values())
        iso = sum(i for *_, i in INDIRECT[e].values())
        f_op, f_tm, f_iso = INDIRECT[e]["Freight"]
        rows.append(dict(hazard=e, Direct=DIRECT[e], Rerouting=rer, Isolation=iso, F_Rerouting=f_op + f_tm, F_Isolation=f_iso,
                         Total=DIRECT[e] + rer + iso, lane_miles=LANE_MILES[e], population=POPULATION[e],
                         freight_value_bn=FREIGHT_VALUE[e]))
    return pd.DataFrame(rows).set_index("hazard")


def _state_weights(e, wobble, seed):
    names, shares = STATES[e]
    w = np.array(shares) * _rng(seed + e).uniform(1 - wobble, 1 + wobble, len(shares))
    return names + ["Rest"], w / w.sum()


def facility_severity():
    """RQ1_1: hazard x class x severity ($B); classes mutually exclusive, rows sum to direct(event)."""
    rows = []
    for e in EVENTS:
        rng = _rng("facility" + e)
        for cls, share in zip(CLASSES, CLASS_SHARE[e]):
            sev = rng.dirichlet(np.ones(3) * 1.4)
            rows.append(dict(hazard=e, facility_type=cls, **{s: DIRECT[e] * share * v for s, v in zip(SEVERITIES, sev)}))
    return pd.DataFrame(rows)


def direct_by_state():
    """RQ1_2(A): leading states' direct damage with min-max band (rank order kept)."""
    rows = []
    for e in EVENTS:
        names, w = _state_weights(e, .03, "direct")
        for rank, (s, v) in enumerate(zip(names[:-1], w[:-1]), start=1):
            d = DIRECT[e] * v
            rows.append(dict(hazard=e, geo_id=s, geo_level="state", geo_scope="affected", rank=rank,
                             Direct=d, Direct_error=d * DAMAGE_BAND, Rerouting=0.0, Isolation=0.0))
    return pd.DataFrame(rows)


def cost_by_state():
    """RQ2(B): top 4 states + Rest, Direct from damage location, indirect attributed to origin state."""
    rows = []
    t = event_totals()
    for e in EVENTS:
        names, wd = _state_weights(e, .03, "direct")
        _, wi = _state_weights(e, .12, "origin")
        for s, d, i in zip(names, wd, wi):
            rows.append(dict(hazard=e, state=s, Direct=t.loc[e, "Direct"] * d,
                             Rerouting=t.loc[e, "Rerouting"] * i, Isolation=t.loc[e, "Isolation"] * i))
    return pd.DataFrame(rows)


def freight_tons_value():
    """RQ3: event x industry tons (Mt) and cargo value ($B) = tons x FAF5 2022 truck $/ton."""
    prices = pd.read_csv(VIZ / "faf5_sctgG5_usd_per_ton.csv").query("year == 2022").set_index("label_resiflow")
    national = (prices.tons_thousand / prices.tons_thousand.sum())[INDUSTRIES].to_numpy()
    tons = pd.DataFrame({e: TONS_MT[e] * _rng("mix" + e).dirichlet(national * 60) for e in EVENTS}, index=INDUSTRIES).T
    value = tons * prices.usd_per_ton[INDUSTRIES].to_numpy() / 1000
    return tons, value


def value_by_state_industry():
    """RQ3(C): cargo value ($B) by top 4 states + Rest x industry; sums to the event x industry value."""
    _, value = freight_tons_value()
    rows = []
    for e in EVENTS:
        names, w = _state_weights(e, .0, "x")
        for ind in INDUSTRIES:
            split = _rng("c" + e + ind).dirichlet(w * 40)
            for s, share in zip(names, split):
                rows.append(dict(hazard=e, state=s, industry=ind, cost=value.loc[e, ind] * share))
    return pd.DataFrame(rows)


def ranked_metrics():
    """RQ1_2(B-E): per-panel numerators (hazard x Direct/Rerouting/Isolation, in $B) and denominators."""
    t = event_totals().reindex(EVENTS)
    full = t[["Direct", "Rerouting", "Isolation"]]
    freight = pd.DataFrame({"Direct": 0.0, "Rerouting": t.F_Rerouting, "Isolation": t.F_Isolation})
    return dict(numerators=[full, full, freight, full],
                denominators=[pd.Series(1.0, index=EVENTS), t.lane_miles, t.freight_value_bn * 1e9, t.population])


def table(row_id):
    """Synthetic table for a registry id, or None if the id is not part of the consistent world."""
    if row_id == "s3_major_cost_panel_a_facility":
        return facility_severity()
    if row_id == "s3_major_cost_panel_b_state":
        return direct_by_state()
    if row_id == "x_sankey_cost_flow_state":
        return cost_by_state()
    if row_id == "x_top5_states_industry":
        return value_by_state_industry()
    if row_id == "s4_freight_passenger_rerouting_isolation":
        t = mode_components()
        rows = []
        for _, r in t.iterrows():
            rows.append(dict(hazard=r.hazard, flow=r.flow, component="Rerouting", cost=(r.Operating + r.Time) * 1000))
            rows.append(dict(hazard=r.hazard, flow=r.flow, component="Isolation", cost=r.Isolation * 1000))
        return pd.DataFrame(rows)
    return None
