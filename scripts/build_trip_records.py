"""
ACDOS — Layer 3: synthetic trip_records generator for RF training.

Combines pickup_zones.csv (spatial baseline) + temporal_calibration.csv
(weekday x hour real calibration grid) into a synthetic historical trip log
matching the ERD schema (Chapter 3.4.3). Documented assumptions below are
flagged inline -- replace with real KQ data per Chapter 3.2.1 without
touching the downstream RF pipeline.

Usage:
    python build_trip_records.py

Output:
    trip_records.csv
"""
import csv
import random
import math
from datetime import datetime, timedelta
from collections import defaultdict

# --------------------------------------------------------------------------
# ASSUMPTIONS -- documented, adjust freely, all flagged as such in the thesis
# --------------------------------------------------------------------------
N_RECORDS = 15000
SIM_START = datetime(2026, 1, 5)   # a Monday; window is 180 days
SIM_DAYS = 180
N_VEHICLES = 20                     # contracted fleet size -- not specified by KQ, assumed
VEHICLE_CAPACITY = 14               # typical 14-seater shuttle van, common in Kenya
NOISE_CV = 0.10                     # lognormal multiplicative noise on calibrated duration
RNG_SEED = 42

# Hour-of-day pickup weights: bimodal around early-morning and evening flight
# banks (Chapter 1.1), light midday tail. Index = hour (0-23).
HOUR_WEIGHTS = [
    3, 3, 4, 6, 8, 7,    # 00-05: early-morning bank builds
    5, 3, 2, 2, 2, 2,    # 06-11: taper into midday
    2, 2, 2, 2, 2, 3,    # 12-17: midday, light afternoon uptick
    5, 7, 8, 6, 4, 3,    # 18-23: evening bank
]

# Route corridor per zone -- grounded in Nairobi's actual major arteries to
# JKIA. First-pass assignment from general geography; sanity-check against
# local knowledge before treating as final.
ROUTE_CORRIDOR = {
    "South B, Nairobi": "Mombasa Road",
    "South C, Nairobi": "Mombasa Road",
    "Embakasi, Nairobi": "Mombasa Road",
    "Imara Daima, Nairobi": "Mombasa Road",
    "Nyayo Estate, Nairobi": "Mombasa Road",
    "Mlolongo, Machakos County": "Mombasa Road",
    "Athi River, Machakos County": "Mombasa Road",
    "Kitengela, Kajiado County": "Mombasa Road",
    "Nairobi CBD, Nairobi": "Uhuru Highway",
    "Upper Hill, Nairobi": "Uhuru Highway",
    "Ngara, Nairobi": "Uhuru Highway",
    "Kilimani, Nairobi": "Uhuru Highway",
    "Lavington, Nairobi": "Uhuru Highway",
    "Westlands, Nairobi": "Uhuru Highway",
    "Runda, Nairobi": "Uhuru Highway",
    "Karen, Nairobi": "Langata Road",
    "Langata, Nairobi": "Langata Road",
    "Ongata Rongai, Kajiado County": "Langata Road",
    "Dagoretti, Nairobi": "Southern Bypass",
    "Kawangware, Nairobi": "Southern Bypass",
    "Buruburu, Nairobi": "Outer Ring/Jogoo Road",
    "Donholm, Nairobi": "Outer Ring/Jogoo Road",
    "Umoja, Nairobi": "Outer Ring/Jogoo Road",
    "Kayole, Nairobi": "Outer Ring/Jogoo Road",
    "Kasarani, Nairobi": "Thika Road/Eastern Bypass",
    "Roysambu, Nairobi": "Thika Road/Eastern Bypass",
    "Kahawa, Nairobi": "Thika Road/Eastern Bypass",
    "Ruiru, Kiambu County": "Thika Road/Eastern Bypass",
}


def load_pickup_zones(path):
    with open(path) as f:
        rows = list(csv.DictReader(f))
    return {r["zone"]: r for r in rows if r["lat"] not in ("", None)}


def load_calibration(path):
    """zone -> weekday -> sorted list of (hour, travel_sec)"""
    data = defaultdict(lambda: defaultdict(list))
    with open(path) as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        if r["travel_sec"] in ("", None):
            continue
        data[r["zone"]][r["weekday"]].append((int(r["hour"]), float(r["travel_sec"])))
    for zone in data:
        for wd in data[zone]:
            data[zone][wd].sort()
    return data


def circular_interp(query_hour, points):
    """Linear interpolation over a 24h circular hour axis.
    points: sorted list of (hour, value)."""
    hours = [h for h, _ in points]
    vals = [v for _, v in points]
    ext_hours = [h - 24 for h in hours] + hours + [h + 24 for h in hours]
    ext_vals = vals * 3
    # simple manual interp (no numpy dependency)
    for i in range(len(ext_hours) - 1):
        if ext_hours[i] <= query_hour <= ext_hours[i + 1]:
            x0, x1 = ext_hours[i], ext_hours[i + 1]
            y0, y1 = ext_vals[i], ext_vals[i + 1]
            if x1 == x0:
                return y0
            frac = (query_hour - x0) / (x1 - x0)
            return y0 + frac * (y1 - y0)
    return vals[0]  # fallback, shouldn't hit given the x3 extension


def main():
    random.seed(RNG_SEED)
    zones_meta = load_pickup_zones("pickup_zones.csv")
    calib = load_calibration("temporal_calibration.csv")

    zone_names = [z for z in zones_meta if z in calib]
    missing = set(zones_meta) - set(calib)
    if missing:
        print(f"[WARN] zones in pickup_zones.csv but not in calibration, skipped: {missing}")

    # static baseline per zone = mean of ALL calibration values for that zone
    static_baseline = {}
    for z in zone_names:
        all_vals = [v for wd_pts in calib[z].values() for _, v in wd_pts]
        static_baseline[z] = sum(all_vals) / len(all_vals)

    weekday_names = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]

    out_rows = []
    for trip_id in range(1, N_RECORDS + 1):
        day_offset = random.randint(0, SIM_DAYS - 1)
        pickup_date = SIM_START + timedelta(days=day_offset)
        weekday_name = weekday_names[pickup_date.weekday()]

        hour = random.choices(range(24), weights=HOUR_WEIGHTS, k=1)[0]
        minute = random.randint(0, 59)
        pickup_ts = pickup_date.replace(hour=hour, minute=minute)
        query_hour = hour + minute / 60.0

        zone = random.choice(zone_names)
        points = calib[zone].get(weekday_name)
        if not points:
            continue
        calibrated_sec = circular_interp(query_hour, points)

        noise = random.lognormvariate(0, NOISE_CV)
        actual_duration_sec = calibrated_sec * noise

        crew_roll = random.random()
        if crew_roll < 0.6:
            crew_count = random.randint(1, 2)
        elif crew_roll < 0.9:
            crew_count = random.randint(3, 6)
        else:
            crew_count = random.randint(7, VEHICLE_CAPACITY)

        vehicle_id = f"VEH-{random.randint(1, N_VEHICLES):03d}"

        actual_arrival = pickup_ts + timedelta(seconds=actual_duration_sec)
        scheduled_report = pickup_ts + timedelta(seconds=static_baseline[zone])

        meta = zones_meta[zone]
        out_rows.append({
            "trip_id": trip_id,
            "pickup_zone": zone,
            "pickup_lat": meta["lat"],
            "pickup_lon": meta["lon"],
            "route_corridor": ROUTE_CORRIDOR.get(zone, "Unclassified"),
            "pickup_timestamp": pickup_ts.isoformat(),
            "day_of_week": weekday_name,
            "hour_of_day": hour,
            "vehicle_id": vehicle_id,
            "crew_count": crew_count,
            "distance_km": meta["straight_line_km"],
            "static_baseline_sec": round(static_baseline[zone], 1),
            "actual_duration_sec": round(actual_duration_sec, 1),
            "actual_arrival_time": actual_arrival.isoformat(),
            "scheduled_report_time": scheduled_report.isoformat(),
            "on_time_under_static_baseline": actual_arrival <= scheduled_report,
        })

    with open("trip_records.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)

    n_ontime = sum(1 for r in out_rows if r["on_time_under_static_baseline"])
    print(f"Generated {len(out_rows)} records across {len(zone_names)} zones, {SIM_DAYS}-day window")
    print(f"On-time rate under the current static-baseline assumption: {100*n_ontime/len(out_rows):.1f}%")
    print("Wrote trip_records.csv")


if __name__ == "__main__":
    main()
