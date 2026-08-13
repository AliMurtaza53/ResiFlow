"""Constants used in the network flow model"""

from resiflow.parameters import get_parameter

CONV_METER_TO_MILE = get_parameter("conversions", "meter_to_mile", 0.000621371)
CONV_MILE_TO_KM = get_parameter("conversions", "mile_to_km", 1.60934)
CONV_KM_TO_MILE = get_parameter("conversions", "km_to_mile", 0.621371)
PENCE_TO_POUND = get_parameter("conversions", "pence_to_pound", 0.01)
GBP_TO_USD = get_parameter("conversions", "gbp_to_usd", 1.27)  # Exchange rate conversion factor (legacy UK cost conversion)

# Average vehicle occupancy for personal (car) travel, used to scale the
# per-vehicle value-of-time into a per-person time cost. Historical source:
# "Vehicle mileage and occupancy, 2021". Centralized here (was previously read
# from a non-existent `parameter_access.united_parameters` in road_revised.py).
AVG_VEHICLE_OCCUPANCY_CAR = get_parameter("cost_time", "avg_vehicle_occupancy_car", 1.1)

# Value of Time in USD per hour (US calibration).
# Source: USDOT "Revised Departmental Guidance on Valuation of Travel Time in
# Economic Analysis" (2022 dollars). Local personal surface travel ~ $18.50/hr;
# local business travel ~ $31.40/hr; truck driver ~ $32.50/hr; intercity
# personal ~ $22.90/hr. Values were previously GBP-derived (UK NIRD) and are
# replaced here with US figures. Dict name kept for backward compatibility;
# see VOT_USD_PER_HOUR alias below.
VOT_POUND_PER_HOUR = get_parameter("cost_time", "vot_usd_per_hour", {
    "car": 18.50,  # USDOT local personal surface travel
    "lgv": 31.00,  # USDOT local business travel (light commercial van)
    "ogv": 32.50,  # USDOT truck-driver value of travel time
    "psv": 18.50,  # transit passenger personal travel
    "rail": 22.90,  # USDOT intercity personal travel
})
# Clearer US-facing alias (same object) for new code.
VOT_USD_PER_HOUR = VOT_POUND_PER_HOUR

# US pump fuel price in USD per litre (2023-2024 national averages).
# Gasoline ~ $3.40/gal = $0.90/L; Diesel ~ $3.95/gal = $1.04/L.
# Replaces the legacy UK assumption of ~1.4 GBP/L * 1.27 = ~$1.78/L.
FUEL_USD_PER_LITRE = get_parameter("cost_operating", "fuel_usd_per_litre", {
    "car": 0.90,  # gasoline
    "lgv": 0.90,  # gasoline (light commercial)
    "ogv": 1.04,  # diesel
    "psv": 1.04,  # diesel
    "rail": 1.04,  # diesel
})
DEFAULT_FUEL_USD_PER_LITRE = get_parameter("conversions", "default_fuel_usd_per_litre", 0.95)

# Fuel consumption in litres per mile (converted from per km)
# Original units: litres per km. Convert by multiplying by CONV_KM_TO_MILE
FUEL_LITRE_PER_KM = get_parameter("cost_operating", "fuel_litre_per_km", {
    "car": {"a": 0.75232, "b": 0.05130, "c": 0.00057, "d": 0.000000372},  # per mile (adjusted)
    "lgv": {"a": 0.65074, "b": 0.09512, "c": -0.00301, "d": 0.000020},  # per mile (adjusted)
    "ogv": {"a": 6.73854, "b": 0.13573, "c": -0.00191, "d": 0.000014},  # per mile (adjusted)
    "psv": {"a": 5.41589, "b": 0.18347, "c": -0.00206, "d": 0.000015},  # per mile (adjusted)
})

# Non-fuel operating costs in cents USD per mile (converted from pence GBP per km)
# Original: pence per km, converted to cents USD per mile
NON_FUEL_PENCE_PER_KM = get_parameter("cost_operating", "non_fuel_cost_coeffs", {
    "car": {"a": 8.74, "b": 239.77},  # cents USD per mile
    "lgv": {"a": 12.70, "b": 83.06},  # cents USD per mile
    "ogv": {"a": 17.41, "b": 680.18},  # cents USD per mile
    "psv": {"a": 53.67, "b": 1223.40},  # cents USD per mile
})
