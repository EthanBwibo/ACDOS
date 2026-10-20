"""
ACDOS — Layer 2 calibration: hour-of-day / day-of-week travel time multipliers.

Queries live Google Distance Matrix (all 28 pickup zones -> JKIA in one call
per time slot) at a spread of future departure times, using Google's
best_guess traffic model (blends historical pattern + live conditions).
This gives real, zone-specific data to ground the synthetic hour/day
multiplier function documented in Chapter 3.2.1, rather than relying on the
CA/KNBS report alone.

Usage:
    python build_temporal_calibration.py YOUR_API_KEY

Output:
    temporal_calibration.csv  (zone, weekday, hour, travel_sec, travel_min)
"""
import sys, csv, json, time as time_module, urllib.request, urllib.parse
from datetime import datetime, timedelta

JKIA_LAT, JKIA_LON = -1.3192, 36.9278

ZONES = [
    "South B, Nairobi", "South C, Nairobi", "Embakasi, Nairobi",
    "Imara Daima, Nairobi", "Nyayo Estate, Nairobi",
    "Karen, Nairobi", "Lavington, Nairobi", "Kilimani, Nairobi",
    "Westlands, Nairobi", "Runda, Nairobi",
    "Buruburu, Nairobi", "Donholm, Nairobi", "Langata, Nairobi",
    "Ruiru, Kiambu County", "Ongata Rongai, Kajiado County",
    "Kitengela, Kajiado County", "Athi River, Machakos County",
    "Kasarani, Nairobi", "Roysambu, Nairobi", "Kahawa, Nairobi",
    "Dagoretti, Nairobi", "Kawangware, Nairobi",
    "Umoja, Nairobi", "Kayole, Nairobi", "Mlolongo, Machakos County",
    "Nairobi CBD, Nairobi", "Upper Hill, Nairobi", "Ngara, Nairobi",
]

# actual weekday -> python weekday() index (Mon=0 ... Sun=6)
WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
# Dense where the traffic curve actually changes shape fast (rush-hour ramps
# and the lunch-hour window); coarse only for genuinely flat overnight blocks.
HOURS = [0, 2, 5, 6, 7, 8, 9, 11, 12, 13, 14, 16, 17, 18, 19, 20, 22]


def next_occurrence(target_weekday, hour):
    now = datetime.now()
    days_ahead = (target_weekday - now.weekday()) % 7
    days_ahead = days_ahead if days_ahead > 0 else 7  # always a future date, not today
    target = (now + timedelta(days=days_ahead)).replace(hour=hour, minute=0, second=0, microsecond=0)
    return target


def geocode_all(zones, key):
    coords = {}
    for z in zones:
        url = "https://maps.googleapis.com/maps/api/geocode/json?" + urllib.parse.urlencode(
            {"address": f"{z}, Kenya", "key": key}
        )
        with urllib.request.urlopen(url) as r:
            data = json.loads(r.read())
        if data["status"] == "OK":
            loc = data["results"][0]["geometry"]["location"]
            coords[z] = (loc["lat"], loc["lng"])
        else:
            print(f"[WARN] geocode failed: {z}")
        time_module.sleep(0.1)
    return coords


def distance_matrix_batch(origins_latlon, dep_unix, key):
    """origins capped at 25 per request; chunk and stitch results back together."""
    results = []
    for i in range(0, len(origins_latlon), 25):
        chunk = origins_latlon[i:i + 25]
        origins_str = "|".join(f"{lat},{lon}" for lat, lon in chunk)
        url = "https://maps.googleapis.com/maps/api/distancematrix/json?" + urllib.parse.urlencode(
            {
                "origins": origins_str,
                "destinations": f"{JKIA_LAT},{JKIA_LON}",
                "departure_time": str(dep_unix),
                "key": key,
            }
        )
        with urllib.request.urlopen(url) as r:
            data = json.loads(r.read())
        if data["status"] != "OK":
            print(f"[WARN] batch request failed: {data['status']}")
            results.extend([None] * len(chunk))
            continue
        for row in data["rows"]:
            el = row["elements"][0]
            if el["status"] == "OK":
                results.append(el.get("duration_in_traffic", el["duration"])["value"])
            else:
                results.append(None)
        time_module.sleep(0.15)
    return results


def main(api_key):
    print("Geocoding zones...")
    coords = geocode_all(ZONES, api_key)
    zone_list = [z for z in ZONES if z in coords]
    origins_latlon = [coords[z] for z in zone_list]

    out_rows = []
    for day_name, weekday in WEEKDAYS.items():
        for hour in HOURS:
            dep = next_occurrence(weekday, hour)
            dep_unix = int(dep.timestamp())
            print(f"{day_name} {hour:02d}:00 ({dep.date()}) ...", end=" ")
            secs = distance_matrix_batch(origins_latlon, dep_unix, api_key)
            for zone, s in zip(zone_list, secs):
                out_rows.append({
                    "zone": zone, "weekday": day_name, "hour": hour,
                    "travel_sec": s, "travel_min": round(s / 60, 1) if s else None,
                })
            print("ok" if all(s is not None for s in secs) else "some failed")
            time_module.sleep(0.3)

    with open("temporal_calibration.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print("\nWrote temporal_calibration.csv")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python build_temporal_calibration.py YOUR_API_KEY")
        sys.exit(1)
    main(sys.argv[1])
