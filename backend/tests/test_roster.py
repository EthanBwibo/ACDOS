"""Reading the roster CSV (#229): the checks that need no database. The
zone and stored-duplicate checks, the fallback to a home location, and the
writes, are in test_roster_imports_postgres.py."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.models.schemas import PickupRequestType, RejectReason
from app.roster import MAX_ROWS, BadFile, parse, pickup_point

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
HEADER = "staff_no,name,crew_role,pickup_location,report_time,request_type"
GOOD = 'KQ1001,Amina Hassan,cabin_crew,"-1.2893, 36.7869",2026-11-20T05:30:00+03:00,rostered'


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


def test_the_location_is_optional_in_the_row_and_as_a_column():
    """#245: a row with none is picked up from home (decided in run())."""
    rows, rejected, _ = parse(csv("KQ1,A,pilot,,2026-11-20T05:30:00+03:00,"), NOW)
    assert rejected == []
    assert (rows[0].lat, rows[0].lon, rows[0].located) == (None, None, False)

    header = "staff_no,name,crew_role,report_time"
    rows, rejected, _ = parse(csv("KQ1,A,pilot,2026-11-20T05:30:00+03:00", header=header), NOW)
    assert rejected == []
    assert rows[0].located is False


def test_request_type_defaults_to_rostered_and_the_column_is_optional():
    header = "staff_no,name,crew_role,pickup_location,report_time"
    rows, _, _ = parse(csv("KQ1,A,pilot,,2026-11-20T05:30:00+03:00", header=header), NOW)
    assert rows[0].request_type is PickupRequestType.ROSTERED

    rows, _, _ = parse(csv("KQ1,A,pilot,,2026-11-20T05:30:00+03:00,"), NOW)
    assert rows[0].request_type is PickupRequestType.ROSTERED

    rows, _, _ = parse(csv("KQ1,A,pilot,,2026-11-20T05:30:00+03:00,Standby"), NOW)
    assert rows[0].request_type is PickupRequestType.STANDBY


def test_an_excel_file_with_a_byte_order_mark_and_crlf_is_read():
    content = ("﻿" + HEADER + "\r\n" + GOOD + "\r\n").encode()

    rows, rejected, _ = parse(content, NOW)

    assert [r.staff_no for r in rows] == ["KQ1001"]
    assert rejected == []


# Google Maps, as a dispatcher would paste it (#245). Each is the same point
# in Westlands: -1.260581, 36.802217.
PIN = (-1.260581, 36.802217)


@pytest.mark.parametrize(
    "value",
    [
        "-1.260581, 36.802217",  # right-click a point, click the coordinates
        "-1.260581,36.802217",
        "  -1.260581 ,  36.802217 ",
        # A place link: the pin is !3d!4d; @ is the view's centre, a little off.
        "https://www.google.com/maps/place/1%C2%B015'38.1%22S+36%C2%B048'08.0%22E/"
        "@-1.2605758,36.7996421,17z/data=!3m1!4b1!4m4!3m3!8m2!3d-1.260581!4d36.802217",
        "https://www.google.com/maps/search/?api=1&query=-1.260581,36.802217",
        "https://www.google.com/maps?q=-1.260581,36.802217",
        "https://maps.google.com/?q=loc:-1.260581,+36.802217",
        "https://www.google.co.ke/maps/place/-1.260581,36.802217",
        "https://www.google.com/maps/search/-1.260581,+36.802217?entry=ttu",
        "https://www.google.com/maps/@-1.260581,36.802217,17z",
        "https://www.google.com/maps/dir/?api=1&destination=-1.260581%2C36.802217",
    ],
    ids=[
        "pasted",
        "no-space",
        "spaces",
        "place-link-pin",
        "api-query",
        "q",
        "maps-host-loc",
        "kenya-domain-place",
        "search-path",
        "view-only",
        "directions",
    ],
)
def test_a_pickup_point_from_google_maps_is_read(value):
    assert pickup_point(value) == PIN


@pytest.mark.parametrize(
    ("value", "reason"),
    [
        ("Westlands", "not a lat, lon pair"),
        ("-1.260581 36.802217", "not a lat, lon pair"),
        ("1°15'38.1\"S 36°48'08.0\"E", "degrees, minutes and seconds aren't read"),
        ("-91, 36.8", "latitude must be between -90 and 90"),
        ("-1.26, 181", "longitude must be between -180 and 180"),
        ("https://maps.app.goo.gl/AbCdEf123", "short maps.app.goo.gl link"),
        ("https://www.openstreetmap.org/#map=17/-1.26/36.80", "not a Google Maps link"),
        ("https://www.google.com/search?q=-1.26,36.80", "not a Google Maps link"),
        ("https://www.google.com/maps/place/Sarit+Centre", "no coordinates in this Google"),
    ],
    ids=[
        "a-name",
        "no-comma",
        "dms",
        "lat-range",
        "lon-range",
        "short-link",
        "other-site",
        "google-search",
        "place-without-point",
    ],
)
def test_anything_else_is_refused_with_the_reason(value, reason):
    with pytest.raises(ValueError, match=reason):
        pickup_point(value)


def test_a_blank_location_is_none():
    assert pickup_point("   ") is None


@pytest.mark.parametrize(
    ("line", "detail"),
    [
        (",Amina,cabin_crew,,2026-11-20T05:30:00+03:00,", "staff_no: missing"),
        ("KQ1,,cabin_crew,,2026-11-20T05:30:00+03:00,", "name: missing"),
        ("KQ1,A,cabin_crew,Kilimani,2026-11-20T05:30:00+03:00,", "pickup_location: not a lat"),
        ('KQ1,A,cabin_crew,"-91, 36.79",2026-11-20T05:30:00+03:00,', "pickup_location: latitude"),
        ("KQ1,A,cabin_crew,,20 Nov 05:30,", "report_time: not an ISO 8601"),
        ("KQ1,A,cabin_crew,,2026-11-20T05:30:00,", "report_time: needs a UTC offset"),
        ("KQ1,A,cabin_crew,,2026-11-20T05:30:00+03:00,charter", "request_type: must"),
        ("KQ1,A,cabin_crew,,2026-11-20T05:30:00+03:00,rostered,extra", "more fields"),
        # Unquoted, the pair's comma splits it into two fields.
        ("KQ1,A,cabin_crew,-1.29, 36.79,2026-11-20T05:30:00+03:00,rostered", "more fields"),
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
    past = "KQ2,B,pilot,,2026-11-16T15:00:00+03:00,"  # 12:00 UTC, so now

    rows, rejected, _ = parse(csv(past), NOW)

    assert rows == []
    assert [(r.line, r.staff_no, r.reason) for r in rejected] == [
        (2, "KQ2", RejectReason.REPORT_TIME_PAST)
    ]


def test_the_same_pickup_twice_in_the_file_keeps_the_first():
    # The same instant, written in UTC the second time.
    again = 'KQ1001,Amina Hassan,cabin_crew,"-1.30, 36.80",2026-11-20T02:30:00Z,rostered'
    later = "KQ1001,Amina Hassan,cabin_crew,,2026-11-21T05:30:00+03:00,rostered"

    rows, rejected, _ = parse(csv(GOOD, again, later), NOW)

    assert [r.line for r in rows] == [2, 4]
    assert [(r.line, r.reason) for r in rejected] == [(3, RejectReason.DUPLICATE_PICKUP)]
    assert rejected[0].detail == "the same pickup is on line 2"


def test_blank_lines_and_rows_of_empty_fields_are_not_rows():
    rows, rejected, count = parse(csv(GOOD, "", ",,,,,"), NOW)

    assert (len(rows), rejected, count) == (1, [], 1)


def test_header_names_ignore_case_and_spaces():
    header = " Staff_No ,NAME,crew_role, Pickup_Location ,report_time"

    rows, _, _ = parse(
        csv('KQ1,A,pilot,"-1.29, 36.79",2026-11-20T05:30:00+03:00', header=header), NOW
    )

    assert (rows[0].staff_no, rows[0].lat) == ("KQ1", -1.29)


@pytest.mark.parametrize(
    ("content", "message"),
    [
        (b"", "the file is empty"),
        (b"\xff\xfe\x00s", "the file is not UTF-8 text"),
        (
            csv(GOOD, header="staff_no,name,pickup_location,report_time"),
            "No crew_role column. Found: staff_no, name, pickup_location, report_time",
        ),
        (
            csv(header="staff_no,name,crew_role,pickup_lat,pickup_lon,report_time"),
            "pickup_lat and pickup_lon were replaced by one pickup_location column",
        ),
        (csv(*[GOOD.replace("KQ1001", f"KQ{i}") for i in range(MAX_ROWS + 1)]), "over 500 rows"),
    ],
    ids=["empty", "not-utf8", "missing-column", "old-lat-lon-columns", "too-many-rows"],
)
def test_a_file_that_cant_be_imported_at_all(content, message):
    with pytest.raises(BadFile, match=message):
        parse(content, NOW)


def test_exactly_500_rows_is_allowed():
    rows, _, count = parse(csv(*[GOOD.replace("KQ1001", f"KQ{i}") for i in range(MAX_ROWS)]), NOW)

    assert count == len(rows) == MAX_ROWS


def _read_as(header: str):
    """GOOD and a standby row with set_home, under the given header, as
    (staff_no, name, crew_role, located, report_time, request_type, set_home)."""
    rows, rejected, _ = parse(
        csv(GOOD + ",", 'KQ2,Brian,pilot,"-1.2, 36.8",2026-11-20T06:00:00+03:00,standby,yes',
            header=header),
        NOW,
    )  # fmt: skip
    assert rejected == []
    return [
        (r.staff_no, r.name, r.crew_role, r.located, r.report_time, r.request_type, r.set_home)
        for r in rows
    ]


EXACT = HEADER + ",set_home"


@pytest.mark.parametrize(
    ("column", "alias"),
    # The table in #254, written out so a dropped alias fails here.
    [
        ("staff_no", "staff number"), ("staff_no", "staff no"), ("staff_no", "staff id"),
        ("staff_no", "employee no"),
        ("crew_role", "role"), ("crew_role", "rank"),
        ("pickup_location", "location"), ("pickup_location", "pickup point"),
        ("pickup_location", "pickup"), ("pickup_location", "coordinates"),
        ("report_time", "report"), ("report_time", "report at"), ("report_time", "duty time"),
        ("request_type", "type"),
        ("set_home", "new home"), ("set_home", "move home"),
    ],
)  # fmt: skip
def test_each_alias_reads_as_its_column(column, alias):
    """#254: a header a spreadsheet already has works without renaming."""
    header = EXACT.replace(column, alias)
    assert header != EXACT
    assert _read_as(header) == _read_as(EXACT)


def test_case_spaces_underscores_and_hyphens_are_ignored_in_headers():
    header = " Staff No ,NAME,Crew-Role,pickup location, REPORT_TIME ,Request Type,SET-HOME"
    assert _read_as(header) == _read_as(EXACT)
    assert _read_as("staff number,Name,Rank,Coordinates,Duty Time,Type,Move Home") == _read_as(
        EXACT
    )


def test_an_unknown_column_is_ignored():
    rows, rejected, _ = parse(csv(GOOD + ",KQ101", header=HEADER + ",Flight"), NOW)
    assert rejected == [] and rows[0].staff_no == "KQ1001"


@pytest.mark.parametrize(
    ("header", "message"),
    [
        ("Name,Role,Location,Report", "No staff_no column. Found: Name, Role, Location, Report"),
        ("Staff No,Location", "No name, crew_role or report_time column. Found: Staff No, "
                              "Location"),
        ("", "the file is empty"),
    ],
)  # fmt: skip
def test_a_missing_column_is_named_with_the_headers_found(header, message):
    with pytest.raises(BadFile, match=f"^{message}$"):
        parse(csv(header=header), NOW)


@pytest.mark.parametrize(
    ("header", "message"),
    [
        (HEADER + ",Role", "crew_role and Role are both the crew_role column: keep one"),
        ("Staff No,staff_no,name,crew_role,report_time", "Staff No and staff_no are both"),
    ],
)
def test_two_headers_for_one_column_are_refused(header, message):
    """Otherwise the file's last such column would be read without a word."""
    with pytest.raises(BadFile, match=message):
        parse(csv(header=header), NOW)


@pytest.mark.parametrize("header", ["Pickup Lat,Pickup Lon", "pickup-lat"])
def test_the_old_lat_lon_columns_are_refused_however_written(header):
    with pytest.raises(BadFile, match="pickup_lat and pickup_lon were replaced"):
        parse(csv(header=f"staff_no,name,crew_role,report_time,{header}"), NOW)


def test_the_template_has_the_exact_headers_and_two_rows_that_read():
    """docs/acdos_roster_template.csv, the file Download template saves."""
    content = (ROOT / "docs" / "acdos_roster_template.csv").read_bytes()
    assert content.decode().splitlines()[0] == (
        "staff_no,name,crew_role,pickup_location,report_time,request_type,set_home"
    )
    rows, rejected, count = parse(content, NOW)
    assert (count, rejected) == (2, [])
    assert [r.located for r in rows] == [False, True]


SET_HOME = HEADER + ",set_home"


def test_set_home_is_optional_and_reads_yes_or_blank():
    rows, rejected, _ = parse(
        csv(
            GOOD + ",yes",
            GOOD.replace("2026-11-20", "2026-11-21") + ",YES",
            GOOD.replace("2026-11-20", "2026-11-22") + ",",
            header=SET_HOME,
        ),
        NOW,
    )

    assert rejected == []
    assert [r.set_home for r in rows] == [True, True, False]
    # Without the column, no row moves a home.
    assert parse(csv(GOOD), NOW)[0][0].set_home is False


def test_set_home_anything_but_yes_or_blank_is_unreadable():
    rows, rejected, _ = parse(csv(GOOD + ",no", header=SET_HOME), NOW)

    assert rows == []
    assert [(r.reason, r.detail) for r in rejected] == [
        (RejectReason.INVALID_ROW, "set_home: must be yes or blank")
    ]


def test_set_home_without_a_location_is_rejected():
    row = "KQ1,A,pilot,,2026-11-20T05:30:00+03:00,,yes"

    rows, rejected, _ = parse(csv(GOOD + ",", row, header=SET_HOME), NOW)

    assert [r.line for r in rows] == [2]
    assert [(r.line, r.staff_no, r.reason, r.detail) for r in rejected] == [
        (
            3,
            "KQ1",
            RejectReason.SET_HOME_NEEDS_LOCATION,
            "set_home: yes needs a pickup_location on the same row",
        )
    ]
