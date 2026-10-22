#!/usr/bin/env python3
"""
Turn the GitHub Actions logger's CSV into one SQL insert for
public.travel_time_observations (#81), to import the rows logged before the
move to Supabase.

Safe to run again: rows already imported are skipped (unique run_id, zone),
so it can be re-run at the cutover to pick up rows logged meanwhile.

Usage:
    git show origin/data-logger:travel_time_log.csv > travel_time_log.csv
    python3 logger/csv_to_sql.py travel_time_log.csv > import.sql
"""

from __future__ import annotations

import csv
import sys

COLUMNS = [
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


def literal(value: str) -> str:
    """A SQL literal; empty CSV cells (failed zones) become null."""
    if value == "":
        return "null"
    return "'" + value.replace("'", "''") + "'"


def to_sql(rows: list[dict]) -> str:
    values = []
    for row in rows:
        row = dict(row)
        # The column holds Nairobi wall-clock time; drop the +03:00 offset.
        row["logged_at_eat"] = row["logged_at_eat"][:19]
        values.append("(" + ", ".join(literal(row[c]) for c in COLUMNS) + ")")
    return (
        f"insert into public.travel_time_observations ({', '.join(COLUMNS)}) values\n"
        + ",\n".join(values)
        + "\non conflict (run_id, zone) do nothing;\n"
    )


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    with open(sys.argv[1], newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise SystemExit("no rows")
    sys.stdout.write(to_sql(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
