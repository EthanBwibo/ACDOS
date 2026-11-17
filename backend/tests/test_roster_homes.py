"""Homes over time in the roster import (#245): _plan_homes without a
database. The connection is a fake that knows the stored homes and names
each point's zone, so the timeline rules are tested here, every run; the
PostGIS zones and the writes are in test_roster_imports_postgres.py.

Rules: a set_home=yes row moves the home from its own report time on,
whatever its line. A row with no location uses the home in effect at its
report time. The stored home ends up as the latest move."""

import asyncio
from datetime import UTC, datetime

import pytest

from app import roster
from app.models.schemas import PickupRequestType
from app.roster import RosterRow, _plan_homes

KILIMANI = (-1.2893, 36.7869)
KASARANI = (-1.221512, 36.892913)
WESTLANDS = (-1.2675, 36.812)
ZONES = {
    KILIMANI: "Kilimani, Nairobi",
    KASARANI: "Kasarani, Nairobi",
    WESTLANDS: "Westlands, Nairobi",
}


class FakeConn:
    """Answers _plan_homes' three queries: stored homes, move zones, home zones."""

    def __init__(self, stored: dict[str, tuple[float, float]]) -> None:
        self.stored = stored

    async def fetch(self, query, *args):
        if "home_location::extensions.geometry" in query:
            return [
                {"staff_no": s, "lat": p[0], "lon": p[1]}
                for s, p in self.stored.items()
                if s in args[0]
            ]
        if query is roster._MOVES:
            alat, alon, blat, blon = args
            return [
                {
                    "i": i,
                    "from_zone": ZONES[(a, b)],
                    "to_zone": ZONES[(c, d)],
                    "distance_km": 1.0,
                }
                for i, (a, b, c, d) in enumerate(zip(alat, alon, blat, blon, strict=True), 1)
            ]
        if query is roster._NEAREST_ZONE:
            lat, lon, _ = args
            return [
                {"i": i, "label": ZONES[p]} for i, p in enumerate(zip(lat, lon, strict=True), 1)
            ]
        raise AssertionError(query)


def day(n: int, hour: int = 5) -> datetime:
    return datetime(2031, 5, n, hour, 30, tzinfo=UTC)


def row(line, report, point=None, set_home=False, staff="S1") -> RosterRow:
    return RosterRow(
        line=line,
        staff_no=staff,
        name="Amina",
        crew_role="cabin_crew",
        lat=point[0] if point else None,
        lon=point[1] if point else None,
        report_time=report,
        request_type=PickupRequestType.ROSTERED,
        set_home=set_home,
    )


def plan(rows, stored=None):
    return asyncio.run(_plan_homes(FakeConn(stored or {}), rows))


ROSTER = [
    row(2, day(5)),  # after the move: Kasarani
    row(3, day(3), KASARANI, set_home=True),  # the move, mid-roster
    row(4, day(1)),  # before it: Kilimani
    row(5, day(4)),  # after it: Kasarani
]


@pytest.mark.parametrize("order", ["as written", "reversed"])
def test_a_mid_roster_move_splits_the_pickups_by_report_time_not_line(order):
    rows = ROSTER if order == "as written" else list(reversed(ROSTER))

    result = plan(rows, stored={"S1": KILIMANI})

    point = {r.line: p for r, p in zip(rows, result.points, strict=True)}
    assert point == {2: KASARANI, 3: KASARANI, 4: KILIMANI, 5: KASARANI}
    assert {u.line: (u.zone_label, u.since) for u in result.uses} == {
        2: ("Kasarani, Nairobi", day(3)),
        4: ("Kilimani, Nairobi", None),
        5: ("Kasarani, Nairobi", day(3)),
    }
    assert result.homes == {"S1": KASARANI}
    assert result.moved == {"S1"}
    [move] = result.moves
    assert (move.line, move.from_zone, move.to_zone, move.takes_effect) == (
        3,
        "Kilimani, Nairobi",
        "Kasarani, Nairobi",
        day(3),
    )


def test_two_moves_chain_by_report_time_and_the_latest_is_the_stored_home():
    rows = [
        row(2, day(4), WESTLANDS, set_home=True),  # the later move, written first
        row(3, day(2), KASARANI, set_home=True),  # the earlier move
        row(4, day(1)),  # Kilimani
        row(5, day(3)),  # Kasarani, from day 2
        row(6, day(5)),  # Westlands, from day 4
    ]

    result = plan(rows, stored={"S1": KILIMANI})

    assert result.points[2:] == [KILIMANI, KASARANI, WESTLANDS]
    assert [(u.line, u.since) for u in result.uses] == [(4, None), (5, day(2)), (6, day(4))]
    assert [(m.line, m.from_zone, m.to_zone) for m in result.moves] == [
        (2, "Kasarani, Nairobi", "Westlands, Nairobi"),
        (3, "Kilimani, Nairobi", "Kasarani, Nairobi"),
    ]
    assert result.homes == {"S1": WESTLANDS}


def test_a_move_at_the_same_report_time_counts_for_that_time():
    """At or before: a move made for this very time applies. (The same staff
    and time twice is a duplicate pickup, so only the move's own row has it;
    a pickup a minute later uses it too.)"""
    rows = [row(2, day(3), KASARANI, set_home=True), row(3, day(3).replace(minute=31))]

    result = plan(rows, stored={"S1": KILIMANI})

    assert result.points == [KASARANI, KASARANI]


def test_without_set_home_a_point_is_for_that_pickup_only():
    rows = [row(2, day(2), KASARANI), row(3, day(3))]

    result = plan(rows, stored={"S1": KILIMANI})

    assert result.points == [KASARANI, KILIMANI]
    assert (result.moved, result.moves, result.homes) == (set(), [], {"S1": KILIMANI})


def test_a_new_crew_member_starts_from_their_first_plain_point():
    """No stored home: the first point without set_home (line order) is it,
    and a set_home row is a move from it, at its own time."""
    rows = [
        row(2, day(1)),  # before the move: the first point
        row(3, day(2), KASARANI, set_home=True),
        row(4, day(5), KILIMANI),  # the first plain point, written after the move
        row(5, day(3)),
    ]

    result = plan(rows)

    assert result.points == [KILIMANI, KASARANI, KILIMANI, KASARANI]
    assert [(m.line, m.from_zone) for m in result.moves] == [(3, "Kilimani, Nairobi")]
    assert result.homes == {"S1": KASARANI}


def test_a_new_crew_member_with_only_set_home_points_starts_from_the_earliest():
    rows = [
        row(2, day(4), KILIMANI, set_home=True),
        row(3, day(2), KASARANI, set_home=True),  # the earliest: their first home
        row(4, day(1)),
        row(5, day(5)),
    ]

    result = plan(rows)

    assert result.points[2:] == [KASARANI, KILIMANI]
    assert [(u.line, u.since) for u in result.uses] == [(4, None), (5, day(4))]
    assert [(m.line, m.from_zone, m.to_zone) for m in result.moves] == [
        (2, "Kasarani, Nairobi", "Kilimani, Nairobi")
    ]
    assert result.homes == {"S1": KILIMANI}


def test_each_crew_member_has_their_own_timeline():
    rows = [
        row(2, day(2), KASARANI, set_home=True, staff="S1"),
        row(3, day(3), staff="S1"),
        row(4, day(3), staff="S2"),
    ]

    result = plan(rows, stored={"S1": KILIMANI, "S2": WESTLANDS})

    assert result.points == [KASARANI, KASARANI, WESTLANDS]
    assert result.homes == {"S1": KASARANI, "S2": WESTLANDS}
    assert result.moved == {"S1"}
