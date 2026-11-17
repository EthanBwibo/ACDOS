"""
ACDOS: regenerate docs/roster_sample.csv, the sample file for the roster
import (#229, #245, docs/roster_import.md), with report times from tomorrow.

The import rejects a row whose report time has passed, so a sample with fixed
dates stops working the day after its last date. Run this before a demo or a
test import:

    python scripts/make_sample_roster.py               dates from tomorrow (Nairobi)
    python scripts/make_sample_roster.py --date 2026-12-01   from that date instead

Most rows have no pickup_location: those crew are picked up from home. Two
new crew members give one, as the dispatcher would paste it from Google
Maps: Amina as coordinates (line 2), Brian as a link (line 4). That point
becomes their home. The last row, line 12, moves Amina's home to Kasarani
with set_home=yes, so a dry run shows "home moves: Kilimani -> Kasarani".
Her rows with no location are then collected from Kasarani.

The file has six good rows and five bad ones, one per reason a row is
rejected, so a dry run shows every reason:

    line 7   duplicate_pickup       line 4 again
    line 8   outside_pickup_zones   a pickup point in Nakuru
    line 9   report_time_past       15 January 2026
    line 10  invalid_row            a report time with no UTC offset
    line 11  no_pickup_location     a new crew member with no location anywhere

Importing it once creates 2 crew and 6 pickups, moves 1 home and rejects 5
rows. A second import of the same file rejects the good rows too, as
duplicate_pickup, and so moves no home.

set_home_needs_location (set_home=yes on a row with no location) isn't in
the sample: it would need a sixth bad row, and the tests cover it.
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
    "pickup_location",
    "report_time",
    "request_type",
    "set_home",
)

# Copied from Google Maps (docs/roster_import.md, "Getting a pickup point from
# Google Maps"): a point near Yaya Centre, Kilimani, as coordinates, and one
# near Sarit Centre, Westlands, as a place link. In the link the pin is
# !3d<lat>!4d<lon>; the @ part is the centre of the map view, a little off.
AMINA_POINT = "-1.292533, 36.787543"
BRIAN_LINK = (
    "https://www.google.com/maps/place/1%C2%B015'38.1%22S+36%C2%B048'08.0%22E/"
    "@-1.2605758,36.7996421,17z/data=!3m1!4b1!4m4!3m3!8m2!3d-1.260581!4d36.802217"
)
NAKURU = "-0.303099, 36.080025"
# Near Kasarani stadium: Amina's new home, 14.1 km from her old one.
KASARANI = "-1.221512, 36.892913"

# (staff_no, name, crew_role, pickup_location, day, report time, request_type,
# and set_home when it is "yes").
# day counts from the first day (0 is that day, 1 the next), or is a fixed
# date. A report time of None is written without an offset (the invalid row).
PAST = date(2026, 1, 15)
GOOD = [
    ("KQ10231", "Amina Hassan", "cabin_crew", AMINA_POINT, 0, "05:30", "rostered"),
    ("KQ10231", "Amina Hassan", "cabin_crew", "", 1, "05:30", "rostered"),
    ("KQ10457", "Brian Mwangi", "pilot", BRIAN_LINK, 0, "06:00", "rostered"),
    ("KQ10457", "Brian Mwangi", "pilot", "", 1, "06:00", ""),
    ("KQ10231", "Amina Hassan", "cabin_crew", "", 2, "07:00", "standby"),
]
BAD = [
    # The same staff number and report time as line 4.
    ("KQ10457", "Brian Mwangi", "pilot", "", 0, "06:00", "rostered"),
    # Nakuru: over 10 km from every pickup zone.
    ("KQ11290", "Esther Kamau", "cabin_crew", NAKURU, 0, "07:30", "rostered"),
    # A fixed date in the past, so it is past whatever --date is.
    ("KQ11317", "Faith Njeri", "cabin_crew", "", PAST, "08:00", "rostered"),
    # No UTC offset: Nairobi time or UTC?
    ("KQ11402", "George Ouma", "pilot", "", 0, None, "rostered"),
    # A new crew member, and no row of theirs gives a location: no home to use.
    ("KQ10892", "Chao Wanjiru", "cabin_crew", "", 0, "06:15", ""),
]


# Amina's home moves to Kasarani: last, so the bad rows keep lines 7 to 11.
MOVE = [
    ("KQ10231", "Amina Hassan", "cabin_crew", KASARANI, 3, "05:30", "rostered", "yes"),
]


def report_time(first_day: date, day: int | date, at: str | None) -> str:
    on = day if isinstance(day, date) else first_day + timedelta(days=day)
    if at is None:
        return datetime.combine(on, time(8, 30)).isoformat()
    hour, minute = (int(part) for part in at.split(":"))
    return datetime.combine(on, time(hour, minute), EAT).isoformat()


def build(first_day: date) -> str:
    """The CSV text, with its report times from first_day. csv quotes the
    locations, which have commas in them, as Excel does."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(HEADER)
    for staff_no, name, role, location, day, at, request_type, *set_home in GOOD + BAD + MOVE:
        writer.writerow(
            (
                staff_no,
                name,
                role,
                location,
                report_time(first_day, day, at),
                request_type,
                *(set_home or [""]),
            )
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
