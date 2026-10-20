"""
ACDOS — build the pickup-zone -> JKIA baseline dataset.

Live Google Distance Matrix queries only. The R&C (2017) grid was tried as a
free supplementary source but rejected: it has a dead zone immediately around
JKIA, several zones show a flat ~18 km/h fallback speed regardless of route
(routing-engine artifact, not real data), and it predates the Nairobi
Expressway. Kept as literature context only (Chapter 2), not as a numeric
source. See decisions-and-learnings.md for the full trail.

Usage:
    python build_pickup_zones.py YOUR_API_KEY

Output:
    pickup_zones.csv
"""
import sys, csv, math, time, json, urllib.request, urllib.parse

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


def geocode(name, key):
    url = "https://maps.googleapis.com/maps/api/geocode/json?" + urllib.parse.urlencode(
        {"address": f"{name}, Kenya", "key": key}
    )
    with urllib.request.urlopen(url) as r:
        data = json.loads(r.read())
    if data["status"] != "OK":
        return None, None
    loc = data["results"][0]["geometry"]["location"]
    return loc["lat"], loc["lng"]


def distance_matrix_to_jkia(lat, lon, key):
    url = "https://maps.googleapis.com/maps/api/distancematrix/json?" + urllib.parse.urlencode(
        {
            "origins": f"{lat},{lon}",
            "destinations": f"{JKIA_LAT},{JKIA_LON}",
            "departure_time": "now",
            "key": key,
        }
    )
    with urllib.request.urlopen(url) as r:
        data = json.loads(r.read())
    try:
        el = data["rows"][0]["elements"][0]
        if el["status"] != "OK":
            return None
        return el.get("duration_in_traffic", el["duration"])["value"]
    except (KeyError, IndexError):
        return None


def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dlmb = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def main(api_key):
    out_rows = []
    for zone in ZONES:
        lat, lon = geocode(zone, api_key)
        if lat is None:
            print(f"[WARN] geocode failed: {zone}")
            out_rows.append({"zone": zone, "lat": None, "lon": None,
                              "jkia_travel_sec": None, "jkia_travel_min": None,
                              "straight_line_km": None})
            continue

        travel_sec = distance_matrix_to_jkia(lat, lon, api_key)
        straight_km = haversine_km(lat, lon, JKIA_LAT, JKIA_LON)
        time.sleep(0.2)  # be polite to the API

        out_rows.append({
            "zone": zone, "lat": round(lat, 6), "lon": round(lon, 6),
            "jkia_travel_sec": travel_sec,
            "jkia_travel_min": round(travel_sec / 60, 1) if travel_sec else None,
            "straight_line_km": round(straight_km, 2),
        })
        status = "OK" if travel_sec else "FAILED"
        print(f"{zone:30s} -> {status:8s} {out_rows[-1]['jkia_travel_min']} min")

    with open("pickup_zones.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(out_rows[0].keys()))
        w.writeheader()
        w.writerows(out_rows)
    print("\nWrote pickup_zones.csv")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python build_pickup_zones.py YOUR_API_KEY")
        sys.exit(1)
    main(sys.argv[1])
