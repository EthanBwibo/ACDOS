"""The sample roster (scripts/make_sample_roster.py, docs/roster_sample.csv):
its bad rows are rejected for the reasons the script says, whatever the date."""

import importlib.util
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

    assert count == 9
    assert [(r.line, r.reason) for r in rejected] == [
        (7, RejectReason.DUPLICATE_PICKUP),
        (9, RejectReason.REPORT_TIME_PAST),
        (10, RejectReason.INVALID_ROW),
    ]
    # Line 8 (Nakuru) passes here: the zone check is in SQL, in run().
    assert [r.line for r in rows] == [2, 3, 4, 5, 6, 8]
    assert rows[-1].staff_no == "KQ11290"


def test_a_later_first_day_still_has_one_past_row():
    now = datetime(2026, 11, 16, 20, 0, tzinfo=sample.EAT)
    _, rejected, _ = parse(sample.build(date(2027, 3, 1)).encode(), now)

    assert [r.reason for r in rejected].count(RejectReason.REPORT_TIME_PAST) == 1


def test_the_checked_in_sample_is_what_the_script_writes():
    text = (ROOT / "docs" / "roster_sample.csv").read_text(encoding="utf-8")
    first_day = date.fromisoformat(text.splitlines()[1].split(",")[5][:10])

    assert text == sample.build(first_day)
