#!/usr/bin/env python3
"""
ACDOS travel time logger.

Queries the Google Distance Matrix API once per run for every pickup zone to
JKIA (departure_time=now, best_guess traffic model) and appends one row per
zone to a CSV. Run hourly, it builds a held-out set of real observed journey
times for validating the Random Forest journey time model.

Standard library only, so the GitHub Actions runner needs no pip install.

Usage:
    python3 logger/log_travel_times.py --zones data/pickup_zones.csv \
        --out logger-data/travel_time_log.csv
    python3 logger/log_travel_times.py --zones data/pickup_zones.csv --dry-run

Environment:
    GOOGLE_MAPS_API_KEY   required unless --dry-run
    JKIA_LAT, JKIA_LON    optional override of the destination coordinate
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

API_URL = "https://maps.googleapis.com/maps/api/distancematrix/json"
EAT = ZoneInfo("Africa/Nairobi")
MAX_ORIGINS_PER_REQUEST = 25  # Distance Matrix limit
RETRYABLE_STATUSES = {"OVER_QUERY_LIMIT", "UNKNOWN_ERROR"}
MAX_ATTEMPTS = 3

# Column aliases accepted in pickup_zones.csv
NAME_COLS = ("zone", "zone_name", "name")
LAT_COLS = ("lat", "latitude")
LON_COLS = ("lon", "lng", "longitude")

OUT_FIELDS = [
    "logged_at_utc",
    "logged_at_eat",
    "day_of_week",
    "hour_eat",
    "minute_eat",
    "zone",
    "origin_lat",
    "origin_lon",
    "element_status",
    "distance_m",
    "duration_sec",
    "duration_in_traffic_sec",
    "run_id",
]


def _pick(header: list[str], options: tuple[str, ...]) -> str:
    lowered = {h.strip().lower(): h for h in header}
    for opt in options:
        if opt in lowered:
            return lowered[opt]
    raise SystemExit(
        f"pickup zones CSV is missing a column named one of {options}; "
        f"found {header}"
    )


def load_zones(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        reader = csv.DictReader(fh)
        header = reader.fieldnames or []
        name_col = _pick(header, NAME_COLS)
        lat_col = _pick(header, LAT_COLS)
        lon_col = _pick(header, LON_COLS)
        zones = [
            {
                "zone": row[name_col].strip(),
                "lat": float(row[lat_col]),
                "lon": float(row[lon_col]),
            }
            for row in reader
            if row[name_col].strip()
        ]
    if not zones:
        raise SystemExit(f"no zones found in {path}")
    return zones


def _request(params: dict) -> dict:
    """GET with retries on network errors and retryable API statuses.
    The URL carries the API key, so it is never printed."""
    url = f"{API_URL}?{urllib.parse.urlencode(params)}"
    last_err = "unknown"
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(url, timeout=30) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_err = f"{type(exc).__name__}: {exc}"
        else:
            status = body.get("status")
            if status == "OK":
                return body
            if status not in RETRYABLE_STATUSES:
                # REQUEST_DENIED, INVALID_REQUEST etc. Retrying will not help.
                raise SystemExit(
                    f"Distance Matrix returned {status}: "
                    f"{body.get('error_message', 'no message')}"
                )
            last_err = status
        if attempt < MAX_ATTEMPTS:
            time.sleep(2 ** attempt)
    raise SystemExit(f"Distance Matrix failed after {MAX_ATTEMPTS} attempts: {last_err}")


def query_batch(zones: list[dict], dest: tuple[float, float], key: str) -> list[dict]:
    params = {
        "origins": "|".join(f"{z['lat']},{z['lon']}" for z in zones),
        "destinations": f"{dest[0]},{dest[1]}",
        "mode": "driving",
        "departure_time": "now",
        "traffic_model": "best_guess",
        "units": "metric",
        "key": key,
    }
    body = _request(params)
    rows = body.get("rows", [])
    if len(rows) != len(zones):
        raise SystemExit(f"expected {len(zones)} rows, got {len(rows)}")
    # One destination, so each row holds exactly one element.
    return [row["elements"][0] for row in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--zones", type=Path, default=Path("data/pickup_zones.csv"))
    ap.add_argument("--out", type=Path, default=Path("logger-data/travel_time_log.csv"))
    ap.add_argument("--dry-run", action="store_true", help="validate inputs, no API call")
    args = ap.parse_args()

    zones = load_zones(args.zones)
    dest = (
        float(os.environ.get("JKIA_LAT", "-1.3192")),
        float(os.environ.get("JKIA_LON", "36.9278")),
    )

    if args.dry_run:
        batches = -(-len(zones) // MAX_ORIGINS_PER_REQUEST)
        print(f"{len(zones)} zones -> JKIA {dest}, {batches} request(s). Dry run, no API call.")
        for z in zones:
            print(f"  {z['zone']}: {z['lat']}, {z['lon']}")
        return 0

    key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
    if not key:
        raise SystemExit("GOOGLE_MAPS_API_KEY is not set")

    # One timestamp per run: every zone in this run shares the same departure time.
    now_utc = datetime.now(timezone.utc).replace(microsecond=0)
    now_eat = now_utc.astimezone(EAT)
    run_id = os.environ.get("GITHUB_RUN_ID", "local")

    out_rows = []
    for i in range(0, len(zones), MAX_ORIGINS_PER_REQUEST):
        batch = zones[i : i + MAX_ORIGINS_PER_REQUEST]
        for zone, el in zip(batch, query_batch(batch, dest, key)):
            status = el.get("status", "MISSING")
            ok = status == "OK"
            out_rows.append(
                {
                    "logged_at_utc": now_utc.isoformat(),
                    "logged_at_eat": now_eat.isoformat(),
                    "day_of_week": now_eat.strftime("%A"),
                    "hour_eat": now_eat.hour,
                    "minute_eat": now_eat.minute,
                    "zone": zone["zone"],
                    "origin_lat": zone["lat"],
                    "origin_lon": zone["lon"],
                    "element_status": status,
                    "distance_m": el["distance"]["value"] if ok else "",
                    "duration_sec": el["duration"]["value"] if ok else "",
                    "duration_in_traffic_sec": (
                        el.get("duration_in_traffic", {}).get("value", "") if ok else ""
                    ),
                    "run_id": run_id,
                }
            )

    args.out.parent.mkdir(parents=True, exist_ok=True)
    new_file = not args.out.exists() or args.out.stat().st_size == 0
    with args.out.open("a", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=OUT_FIELDS)
        if new_file:
            writer.writeheader()
        writer.writerows(out_rows)

    ok_count = sum(r["element_status"] == "OK" for r in out_rows)
    print(f"{now_eat:%a %Y-%m-%d %H:%M} EAT: {ok_count}/{len(out_rows)} zones OK -> {args.out}")
    # Fail the job (red run plus email) only if nothing usable came back.
    return 0 if ok_count else 1


if __name__ == "__main__":
    sys.exit(main())
