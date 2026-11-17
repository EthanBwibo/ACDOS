"""The sample roster (scripts/make_sample_roster.py, docs/roster_sample.csv):
its bad rows are rejected for the reasons the script says, whatever the date.
The whole import of it, zone checks included, is in
test_roster_imports_postgres.py."""

import csv
import importlib.util
import io
from datetime import date, datetime, timedelta
from pathlib import Path

from app.models.schemas import RejectReason
from app.roster import parse

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "make_sample_roster", ROOT / "scripts" / "make_sample_roster.py"
)
sample = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sample)


def test_the_bad_rows_are_rejected_and_the_good_ones_pass():
    now = datetime(2026, 11, 16, 20, 0, tzinfo=sample.EAT)
    rows, rejected, count = parse(sample.build(now.date() + timedelta(days=1)).encode(), now)

    assert count == 11
    assert [(r.line, r.reason) for r in rejected] == [
        (7, RejectReason.DUPLICATE_PICKUP),
        (9, RejectReason.REPORT_TIME_PAST),
        (10, RejectReason.INVALID_ROW),
    ]
    # Line 8 (Nakuru) and line 11 (no location) pass here: the zone and home
    # checks need the database, in run().
    assert [r.line for r in rows] == [2, 3, 4, 5, 6, 8, 11, 12]


def test_most_rows_have_no_location_and_two_are_pasted_from_google_maps():
    now = datetime(2026, 11, 16, 20, 0, tzinfo=sample.EAT)
    rows, _, _ = parse(sample.build(now.date() + timedelta(days=1)).encode(), now)

    points = {r.line: (r.lat, r.lon) for r in rows if r.located}
    # Line 4's link gives its pin, not the @ centre of the map view.
    assert points == {
        2: (-1.292533, 36.787543),
        4: (-1.260581, 36.802217),
        8: (-0.303099, 36.080025),
        12: (-1.221512, 36.892913),
    }
    # Only line 12 moves a home: Amina's, to Kasarani.
    assert [(r.line, r.staff_no) for r in rows if r.set_home] == [(12, "KQ10231")]
    # Most of the file's rows have no location (7 of 11).
    text = sample.build(now.date() + timedelta(days=1))
    blank = [r for r in csv.DictReader(io.StringIO(text)) if not r["pickup_location"]]
    assert len(blank) * 2 > text.count("\n") - 1


def test_a_later_first_day_still_has_one_past_row():
    now = datetime(2026, 11, 16, 20, 0, tzinfo=sample.EAT)
    _, rejected, _ = parse(sample.build(date(2027, 3, 1)).encode(), now)

    assert [r.reason for r in rejected].count(RejectReason.REPORT_TIME_PAST) == 1


def test_the_checked_in_sample_is_what_the_script_writes():
    text = (ROOT / "docs" / "roster_sample.csv").read_text(encoding="utf-8")
    first_row = next(csv.DictReader(io.StringIO(text)))
    first_day = date.fromisoformat(first_row["report_time"][:10])

    assert text == sample.build(first_day)
