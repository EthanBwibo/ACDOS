"""Reading the roster CSV (#229): the checks that need no database. The
zone and stored-duplicate checks, and the writes, are in
test_roster_imports_postgres.py."""

from datetime import UTC, datetime

import pytest

from app.models.schemas import PickupRequestType, RejectReason
from app.roster import MAX_ROWS, BadFile, parse

NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
HEADER = "staff_no,name,crew_role,pickup_lat,pickup_lon,report_time,request_type"
GOOD = "KQ1001,Amina Hassan,cabin_crew,-1.2893,36.7869,2026-11-20T05:30:00+03:00,rostered"


def csv(*lines: str, header: str = HEADER) -> bytes:
    return "\n".join([header, *lines]).encode()


def test_a_good_row_is_read_with_its_offset():
    rows, rejected, count = parse(csv(GOOD), NOW)

    assert rejected == []
    assert count == 1
    row = rows[0]
    assert (row.line, row.staff_no, row.name, row.crew_role) == (
        2,
        "KQ1001",
        "Amina Hassan",
        "cabin_crew",
    )
    assert (row.lat, row.lon) == (-1.2893, 36.7869)
    assert row.report_time == datetime(2026, 11, 20, 2, 30, tzinfo=UTC)
    assert row.request_type is PickupRequestType.ROSTERED


def test_request_type_defaults_to_rostered_and_the_column_is_optional():
    header = "staff_no,name,crew_role,pickup_lat,pickup_lon,report_time"
    rows, _, _ = parse(csv("KQ1,A,pilot,-1.29,36.79,2026-11-20T05:30:00+03:00", header=header), NOW)
    assert rows[0].request_type is PickupRequestType.ROSTERED

    rows, _, _ = parse(csv("KQ1,A,pilot,-1.29,36.79,2026-11-20T05:30:00+03:00,"), NOW)
    assert rows[0].request_type is PickupRequestType.ROSTERED

    rows, _, _ = parse(csv("KQ1,A,pilot,-1.29,36.79,2026-11-20T05:30:00+03:00,Standby"), NOW)
    assert rows[0].request_type is PickupRequestType.STANDBY


def test_an_excel_file_with_a_byte_order_mark_and_crlf_is_read():
    content = ("﻿" + HEADER + "\r\n" + GOOD + "\r\n").encode()

    rows, rejected, _ = parse(content, NOW)

    assert [r.staff_no for r in rows] == ["KQ1001"]
    assert rejected == []


@pytest.mark.parametrize(
    ("line", "detail"),
    [
        (",Amina,cabin_crew,-1.29,36.79,2026-11-20T05:30:00+03:00,", "staff_no: missing"),
        ("KQ1,,cabin_crew,-1.29,36.79,2026-11-20T05:30:00+03:00,", "name: missing"),
        ("KQ1,A,cabin_crew,south,36.79,2026-11-20T05:30:00+03:00,", "pickup_lat: not a number"),
        ("KQ1,A,cabin_crew,-91,36.79,2026-11-20T05:30:00+03:00,", "pickup_lat: must be between"),
        ("KQ1,A,cabin_crew,-1.29,nan,2026-11-20T05:30:00+03:00,", "pickup_lon: must be between"),
        ("KQ1,A,cabin_crew,-1.29,36.79,20 Nov 05:30,", "report_time: not an ISO 8601"),
        ("KQ1,A,cabin_crew,-1.29,36.79,2026-11-20T05:30:00,", "report_time: needs a UTC offset"),
        ("KQ1,A,cabin_crew,-1.29,36.79,2026-11-20T05:30:00+03:00,charter", "request_type: must"),
        ("KQ1,A,cabin_crew,-1.29,36.79,2026-11-20T05:30:00+03:00,rostered,extra", "more fields"),
    ],
)
def test_an_unreadable_row_is_rejected_with_its_line_and_the_rest_still_read(line, detail):
    rows, rejected, count = parse(csv(GOOD, line), NOW)

    assert [r.staff_no for r in rows] == ["KQ1001"]
    assert count == 2
    assert len(rejected) == 1
    assert rejected[0].line == 3
    assert rejected[0].reason is RejectReason.INVALID_ROW
    assert rejected[0].detail.startswith(detail)


def test_a_report_time_already_past_is_rejected():
    past = "KQ2,B,pilot,-1.29,36.79,2026-11-16T15:00:00+03:00,"  # 12:00 UTC, so now

    rows, rejected, _ = parse(csv(past), NOW)

    assert rows == []
    assert [(r.line, r.staff_no, r.reason) for r in rejected] == [
        (2, "KQ2", RejectReason.REPORT_TIME_PAST)
    ]


def test_the_same_pickup_twice_in_the_file_keeps_the_first():
    # The same instant, written in UTC the second time.
    again = "KQ1001,Amina Hassan,cabin_crew,-1.30,36.80,2026-11-20T02:30:00Z,rostered"
    later = "KQ1001,Amina Hassan,cabin_crew,-1.29,36.79,2026-11-21T05:30:00+03:00,rostered"

    rows, rejected, _ = parse(csv(GOOD, again, later), NOW)

    assert [r.line for r in rows] == [2, 4]
    assert [(r.line, r.reason) for r in rejected] == [(3, RejectReason.DUPLICATE_PICKUP)]
    assert rejected[0].detail == "the same pickup is on line 2"


def test_blank_lines_and_rows_of_empty_fields_are_not_rows():
    rows, rejected, count = parse(csv(GOOD, "", ",,,,,,"), NOW)

    assert (len(rows), rejected, count) == (1, [], 1)


def test_header_names_ignore_case_and_spaces():
    header = " Staff_No ,NAME,crew_role,pickup_lat,pickup_lon,report_time"

    rows, _, _ = parse(csv("KQ1,A,pilot,-1.29,36.79,2026-11-20T05:30:00+03:00", header=header), NOW)

    assert rows[0].staff_no == "KQ1"


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "the file is empty"),
        (b"\xff\xfe\x00s", "the file is not UTF-8 text"),
        (csv(GOOD, header="staff_no,name,pickup_lat,pickup_lon"), "missing columns: crew_role"),
        (csv(*[GOOD.replace("KQ1001", f"KQ{i}") for i in range(MAX_ROWS + 1)]), "over 500 rows"),
    ],
    ids=["empty", "not-utf8", "missing-column", "too-many-rows"],
)
def test_a_file_that_cant_be_imported_at_all(content, message):
    with pytest.raises(BadFile, match=message):
        parse(content, NOW)


def test_exactly_500_rows_is_allowed():
    rows, _, count = parse(csv(*[GOOD.replace("KQ1001", f"KQ{i}") for i in range(MAX_ROWS)]), NOW)

    assert count == len(rows) == MAX_ROWS
