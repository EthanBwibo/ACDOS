"""The defence day generator (#252, scripts/make_defence_day.py), without a
database: deterministic, band shares, locations, and a roster file the
import reads as the script says. Seed and reset against Postgres are in
test_defence_day_postgres.py."""

import importlib.util
import math
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

from app.models.schemas import RejectReason
from app.roster import parse

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "make_defence_day", ROOT / "scripts" / "make_defence_day.py"
)
defence = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(defence)

DAY = date(2026, 11, 20)
NOW = datetime(2026, 11, 19, 20, 0, tzinfo=defence.EAT)


def km(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Haversine distance: the test checks the generator's flat-Earth offsets."""
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371 * math.asin(math.sqrt(h))


def test_the_same_date_and_seed_give_the_same_day():
    assert defence.build_roster(DAY, 7) == defence.build_roster(DAY, 7)
    assert defence.build_roster(DAY, 7) != defence.build_roster(DAY, 8)
    assert defence.build_pickups(DAY, 7) != defence.build_pickups(DAY + timedelta(days=1), 7)
    # The crew are standing data: the same whatever the day.
    assert defence.build_crew(7) == defence.build_crew(7)


def test_band_shares_are_within_three_points():
    for seed in (1, 252, 999):
        pickups = defence.build_pickups(DAY, seed)
        assert len(pickups) == 120
        counts = Counter(p.band for p in pickups)
        for band, share in [("early", 35), ("mid", 20), ("noon", 15), ("afternoon", 15),
                            ("night", 15)]:  # fmt: skip
            assert abs(100 * counts[band] / len(pickups) - share) <= 3, (seed, band)


def test_report_times_fall_in_their_band_on_the_day():
    for p in defence.build_pickups(DAY):
        band = defence.BAND[p.band]
        assert p.report.date() == DAY and p.report.utcoffset() == timedelta(hours=3)
        assert band.start <= p.report.time() <= band.end
        assert p.report.minute % 5 == 0


def test_every_location_is_within_10_km_of_a_zone():
    zones = list(defence.accounts.zone_points().values())
    points = [(c.lat, c.lon) for c in defence.build_crew()]
    points += [p.point for p in defence.build_pickups(DAY) if p.point]
    assert len(points) == 120 + 5
    for point in points:
        assert min(km(point, z) for z in zones) < 10, point


def test_120_crew_across_the_28_zones_with_the_named_crew_among_them():
    crew = defence.build_crew()
    assert len(crew) == 120
    assert len({c.staff_no for c in crew}) == 120
    assert len({c.name for c in crew}) == 120
    assert len({c.zone for c in crew}) == 28
    tagged = [c for c in crew if c.name.startswith("defence-")]
    assert len(tagged) == 112
    named = {c.staff_no: c for c in defence.accounts.NAMED_CREW}
    assert {c.staff_no for c in crew if not c.name.startswith("defence-")} == set(named)

    # Each named crew member has a pickup in each of their bands, and only those.
    pickups = defence.build_pickups(DAY)
    for staff_no, c in named.items():
        assert sorted(p.band for p in pickups if p.staff_no == staff_no) == sorted(c.bands)


def test_some_crew_have_two_pickups_in_bands_apart_and_a_few_are_standby():
    pickups = defence.build_pickups(DAY)
    order = [b.key for b in defence.BANDS]
    bands: dict[str, list[str]] = {}
    for p in pickups:
        bands.setdefault(p.staff_no, []).append(p.band)
    twice = {s: b for s, b in bands.items() if len(b) == 2}
    assert len(twice) == 9  # Brian and 8 generated crew
    assert all(abs(order.index(a) - order.index(b)) >= 2 for a, b in twice.values())
    assert max(len(b) for b in bands.values()) == 2
    assert Counter(p.request_type for p in pickups) == {"rostered": 114, "standby": 6}


def test_the_import_reads_the_roster_as_the_script_says():
    rows, rejected, count = parse(defence.build_roster(DAY).encode(), NOW)
    assert count == 124
    # The Nakuru row (line 123) passes the parse: the zone check needs the
    # database. The other three bad rows are rejected here.
    assert [(r.line, r.reason) for r in rejected] == [
        (122, RejectReason.DUPLICATE_PICKUP),
        (124, RejectReason.REPORT_TIME_PAST),
        (125, RejectReason.INVALID_ROW),
    ]
    assert [r.line for r in rows] == [*range(2, 122), 123]
    good = rows[:120]
    assert sum(not r.located for r in good) == 115  # mostly from home
    assert sum(r.set_home for r in good) == 1
    assert (rows[-1].lat, rows[-1].lon) == defence.NAKURU
    text = defence.build_roster(DAY)
    assert text.count("google.com/maps") == 1


def test_each_band_has_its_own_vans():
    groups = defence.VAN_GROUPS
    assert [len(groups[b.key]) for b in defence.BANDS] == [7, 4, 3, 3, 3]
    plates = [p for g in groups.values() for p, _ in g]
    assert plates == [p for p, _, _ in defence.accounts.DEFENCE_VANS]
    # Enough seats for each band.
    for b in defence.BANDS:
        assert b.vans * defence.CAPACITY >= b.pickups


def test_the_committed_roster_is_one_the_script_writes():
    text = (ROOT / "docs" / "defence_roster.csv").read_text(encoding="utf-8")
    day = date.fromisoformat(text.splitlines()[1].split(",")[4][:10])
    assert text == defence.build_roster(day)
