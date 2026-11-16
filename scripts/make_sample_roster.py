"""
ACDOS: regenerate docs/roster_sample.csv, the sample file for the roster
import (#229, docs/roster_import.md), with report times from tomorrow.

The import rejects a row whose report time has passed, so a sample with fixed
dates stops working the day after its last date. Run this before a demo or a
test import:

    python scripts/make_sample_roster.py               dates from tomorrow (Nairobi)
    python scripts/make_sample_roster.py --date 2026-12-01   from that date instead

The file has five good rows and four bad ones, one per reason a row is
rejected, so a dry run shows every reason:

    line 7   duplicate_pickup       line 4 again
    line 8   outside_pickup_zones   a pickup point in Nakuru
    line 9   report_time_past       15 January 2026
    line 10  invalid_row            a report time with no UTC offset

Importing it once creates 4 crew and 5 pickups and rejects 4 rows. A second
import of the same file rejects the good rows too, as duplicate_pickup.
"""

import argparse
import csv
import io
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

# Nairobi time. A fixed offset, as in backend/app/jobs/worker.py: Kenya has no
# daylight saving, and Windows has no time zone database without tzdata.
EAT = timezone(timedelta(hours=3), "EAT")

OUT = Path(__file__).resolve().parent.parent / "docs" / "roster_sample.csv"

HEADER = (
    "staff_no",
    "name",
    "crew_role",
    "pickup_lat",
    "pickup_lon",
    "report_time",
    "request_type",
)

# (staff_no, name, crew_role, lat, lon, day, report time, request_type).
# day counts from the first day (0 is that day, 1 the next), or is a fixed
# date. A report time of None is written without an offset (the invalid row).
PAST = date(2026, 1, 15)
GOOD = [
    ("KQ10231", "Amina Hassan", "cabin_crew", -1.289279, 36.786931, 0, "05:30", "rostered"),
    ("KQ10231", "Amina Hassan", "cabin_crew", -1.289279, 36.786931, 1, "05:30", "rostered"),
    ("KQ10457", "Brian Mwangi", "pilot", -1.2675, 36.812022, 0, "06:00", "rostered"),
    ("KQ10892", "Chao Wanjiru", "cabin_crew", -1.292248, 36.881548, 0, "06:15", ""),
    ("KQ11044", "Daniel Otieno", "cabin_crew", -1.323994, 36.667803, 0, "07:00", "standby"),
]
BAD = [
    # The same staff number and report time as line 4.
    ("KQ10457", "Brian Mwangi", "pilot", -1.2675, 36.812022, 0, "06:00", "rostered"),
    # Nakuru: over 10 km from every pickup zone.
    ("KQ11290", "Esther Kamau", "cabin_crew", -0.303099, 36.080025, 0, "07:30", "rostered"),
    # A fixed date in the past, so it is past whatever --date is.
    ("KQ11317", "Faith Njeri", "cabin_crew", -1.300312, 36.776126, PAST, "08:00", "rostered"),
    # No UTC offset: Nairobi time or UTC?
    ("KQ11402", "George Ouma", "pilot", -1.231577, 36.891548, 0, None, "rostered"),
]


def report_time(first_day: date, day: int | date, at: str | None) -> str:
    on = day if isinstance(day, date) else first_day + timedelta(days=day)
    if at is None:
        return datetime.combine(on, time(8, 30)).isoformat()
    hour, minute = (int(part) for part in at.split(":"))
    return datetime.combine(on, time(hour, minute), EAT).isoformat()


def build(first_day: date) -> str:
    """The CSV text, with its report times from first_day."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(HEADER)
    for staff_no, name, role, lat, lon, day, at, request_type in GOOD + BAD:
        writer.writerow(
            (staff_no, name, role, lat, lon, report_time(first_day, day, at), request_type)
        )
    return out.getvalue()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--date",
        type=date.fromisoformat,
        default=datetime.now(EAT).date() + timedelta(days=1),
        help="the first day's date, YYYY-MM-DD (default: tomorrow in Nairobi)",
    )
    args = parser.parse_args()
    OUT.write_text(build(args.date), encoding="utf-8", newline="")
    print(f"wrote {OUT} with report times from {args.date}")


if __name__ == "__main__":
    main()
