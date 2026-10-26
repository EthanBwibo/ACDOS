"""
ACDOS — zone-to-zone travel matrix for pickup-to-pickup legs (#102, part of #23).

One-off Google Distance Matrix query between the 28 pickup zones of
data/pickup_zones.csv (the same points the hourly logger uses), at three
departure times on one Monday-to-Thursday date, Nairobi time (EAT, UTC+3):

    05:00  off_peak      L2's quietest weekday hour (temporal_calibration.csv)
    18:00  evening_peak  L2's busiest hour
    07:30  morning_peak  held out: only used to check the model (zone_matrix.py)

Traffic model best_guess, as for Layer 2 (build_temporal_calibration.py).
28 x 28 x 3 = 2,352 elements in 42 requests of 4 origins x 14 destinations.

The key is read from the GOOGLE_MAPS_API_KEY environment variable. Passing it
as the first argument still works, with a warning: command lines are kept in
shell history.

Usage (from the repo root):
    python scripts/build_zone_matrix.py --dry-run
    python scripts/build_zone_matrix.py [--date YYYY-MM-DD]
    python scripts/build_zone_matrix.py --add held_out_0830 08:30   (#106)

--add queries one more departure on the date already in data/zone_matrix.csv
and appends it, leaving the existing rows untouched (#106).

Output:
    data/zone_matrix.csv (refuses to overwrite it unless --force)
"""
import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, date, datetime, timedelta, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ZONES_CSV = REPO / "data" / "pickup_zones.csv"
OUT_CSV = REPO / "data" / "zone_matrix.csv"

EAT = timezone(timedelta(hours=3))  # Kenya keeps no daylight saving time
PERIODS = [("off_peak", 5, 0), ("evening_peak", 18, 0), ("morning_peak", 7, 30)]
QUERY_WEEKDAYS = (0, 1, 2, 3)  # Monday to Thursday
ORIGINS_PER_REQUEST = 4
DESTINATIONS_PER_REQUEST = 14  # 4 x 14 = 56, under the 100-element limit
URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
COLUMNS = [
    "period", "departure_eat", "origin_zone", "dest_zone",
    "distance_m", "duration_sec", "duration_in_traffic_sec", "queried_at_utc",
]


def load_zones():
    with ZONES_CSV.open(newline="", encoding="utf-8") as f:
        return [(r["zone"], float(r["lat"]), float(r["lon"])) for r in csv.DictReader(f)]


def default_date(today):
    """The next Tuesday, Wednesday or Thursday at least a day ahead."""
    day = today + timedelta(days=1)
    while day.weekday() not in (1, 2, 3):
        day += timedelta(days=1)
    return day


def departures(query_date):
    return [
        (period, datetime(query_date.year, query_date.month, query_date.day, h, m, tzinfo=EAT))
        for period, h, m in PERIODS
    ]


def chunks(items, size):
    return [items[i:i + size] for i in range(0, len(items), size)]


def request(origins, destinations, depart, key):
    """One Distance Matrix request. Errors are reported without the URL, which
    carries the key."""
    params = {
        "origins": "|".join(f"{lat},{lon}" for _, lat, lon in origins),
        "destinations": "|".join(f"{lat},{lon}" for _, lat, lon in destinations),
        "departure_time": str(int(depart.timestamp())),
        "traffic_model": "best_guess",
        "key": key,
    }
    for attempt in (1, 2):
        try:
            with urllib.request.urlopen(f"{URL}?{urllib.parse.urlencode(params)}", timeout=30) as r:
                data = json.loads(r.read())
        except (urllib.error.URLError, TimeoutError) as e:
            reason = getattr(e, "code", None) or type(e).__name__
            data = {"status": f"request failed ({reason})"}
        if data.get("status") == "OK":
            return data
        if attempt == 1:
            time.sleep(2)
    message = data.get("error_message", "")
    sys.exit(f"Distance Matrix request failed: {data.get('status')} {message}. Nothing written.")


def query(plan, zones, key):
    """Every pair of zones at each departure in plan; nothing is written here."""
    rows, failed = [], 0
    for period, depart in plan:
        print(f"{period} {depart:%H:%M} ...", end=" ", flush=True)
        for origins in chunks(zones, ORIGINS_PER_REQUEST):
            for destinations in chunks(zones, DESTINATIONS_PER_REQUEST):
                data = request(origins, destinations, depart, key)
                queried = datetime.now(UTC).isoformat(timespec="seconds")
                for origin, row in zip(origins, data["rows"]):
                    for dest, element in zip(destinations, row["elements"]):
                        ok = element.get("status") == "OK"
                        failed += not ok
                        rows.append({
                            "period": period,
                            "departure_eat": depart.strftime("%Y-%m-%dT%H:%M"),
                            "origin_zone": origin[0],
                            "dest_zone": dest[0],
                            "distance_m": element["distance"]["value"] if ok else "",
                            "duration_sec": element["duration"]["value"] if ok else "",
                            "duration_in_traffic_sec": (
                                element.get("duration_in_traffic", {}).get("value", "")
                                if ok
                                else ""
                            ),
                            "queried_at_utc": queried,
                        })
                time.sleep(0.2)
        print("ok")
    return rows, failed


def existing_matrix():
    """Periods and the single query date already in data/zone_matrix.csv."""
    with OUT_CSV.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    dates = {r["departure_eat"][:10] for r in rows}
    if len(dates) != 1:
        sys.exit(f"{OUT_CSV} holds more than one query date: {sorted(dates)}")
    return {r["period"] for r in rows}, date.fromisoformat(dates.pop())


def get_key(args):
    key = os.environ.get("GOOGLE_MAPS_API_KEY")
    if not key and args.key:
        print("WARNING: key taken from the command line, which is kept in shell history. "
              "Set GOOGLE_MAPS_API_KEY instead.", file=sys.stderr)
        key = args.key
    if not key:
        sys.exit("Set GOOGLE_MAPS_API_KEY first (see the docstring).")
    return key


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("key", nargs="?", help="fallback only: prefer GOOGLE_MAPS_API_KEY")
    parser.add_argument("--date", type=date.fromisoformat, help="query date (Mon-Thu), YYYY-MM-DD")
    parser.add_argument(
        "--add", nargs=2, metavar=("PERIOD", "HH:MM"),
        help="query one more departure on the existing file's date and append it (#106)",
    )  # fmt: skip
    parser.add_argument("--dry-run", action="store_true", help="print the plan, query nothing")
    parser.add_argument("--force", action="store_true", help="overwrite data/zone_matrix.csv")
    args = parser.parse_args()

    zones = load_zones()
    if args.add:
        if not OUT_CSV.exists():
            sys.exit(f"--add appends to {OUT_CSV}, which does not exist yet.")
        period, at = args.add
        periods, query_date = existing_matrix()
        if args.date and args.date != query_date:
            sys.exit(f"--add queries on the file's own date, {query_date}, not {args.date}.")
        if period in periods:
            sys.exit(f"{OUT_CSV} already has a {period} matrix.")
        hour, minute = (int(x) for x in at.split(":"))
        plan = [(period, datetime(query_date.year, query_date.month, query_date.day,
                                  hour, minute, tzinfo=EAT))]  # fmt: skip
    else:
        query_date = args.date or default_date(datetime.now(EAT).date())
        plan = departures(query_date)
        if query_date.weekday() not in QUERY_WEEKDAYS:
            sys.exit(
                f"{query_date} is a {query_date:%A}: the query date must be Monday to Thursday."
            )
    if min(depart for _, depart in plan) <= datetime.now(EAT):
        sys.exit(f"Every departure on {query_date} must be in the future: pick a later date.")

    n_requests = (
        len(plan) * len(chunks(zones, ORIGINS_PER_REQUEST))
        * len(chunks(zones, DESTINATIONS_PER_REQUEST))
    )  # fmt: skip
    print(f"{len(zones)} zones, {query_date:%A %d %B %Y}:")
    for period, depart in plan:
        print(f"  {period:<13} {depart:%H:%M} EAT")
    action = "appended to" if args.add else "->"
    print(f"{n_requests} requests, {len(plan) * len(zones) ** 2} elements {action} {OUT_CSV}")
    if args.dry_run:
        return

    key = get_key(args)
    if not args.add and OUT_CSV.exists() and not args.force:
        sys.exit(f"{OUT_CSV} exists; pass --force to query again and overwrite it.")
    rows, failed = query(plan, zones, key)

    # Written only once every request has succeeded (request() exits otherwise).
    with OUT_CSV.open("a" if args.add else "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        if not args.add:
            writer.writeheader()
        writer.writerows(rows)
    missing_traffic = sum(
        1 for r in rows if r["duration_sec"] != "" and r["duration_in_traffic_sec"] == ""
    )
    print(f"Wrote {len(rows)} rows to {OUT_CSV}: {failed} failed elements, "
          f"{missing_traffic} without duration_in_traffic.")


if __name__ == "__main__":
    main()
