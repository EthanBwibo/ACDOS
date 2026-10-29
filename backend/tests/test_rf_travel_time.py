"""The solver's travel time from the RF and the zone matrix (#104)."""

import random
from datetime import datetime, timedelta

import pytest

from app.jobs import worker
from app.ml import journey_time, travel_time, zone_matrix
from app.ml.journey_time import HourlyGrid
from app.solver import insertion
from app.solver.ga import solve
from app.solver.individual import _drive
from app.solver.instances import smoke_30
from app.solver.problem import JKIA, Pickup, Point, Problem, Vehicle
from app.solver.weights import SOLOMON
from tests.solver_checks import assert_feasible
from tests.test_zone_matrix import write_files

ZONES = {"A": Point(-1.30, 36.80), "B": Point(-1.30, 36.90), "C": Point(-1.20, 36.85)}
TUESDAY_0300 = datetime(2026, 10, 27, 3, 0)  # the zone matrix fixture's query day


def grid(offset=0):
    """RF predictions easy to read: 1000 per zone letter + 100 x weekday + hour."""
    return HourlyGrid(
        {
            (z, d, h): 1000 * (k + 1) + 100 * d + h + offset
            for k, z in enumerate("ABC")
            for d in range(7)
            for h in range(24)
        }
    )


@pytest.fixture
def matrix(tmp_path):
    return zone_matrix.load(*write_files(tmp_path))


@pytest.fixture
def travel(matrix):
    return travel_time.rf_travel_time(grid(), matrix, ZONES, TUESDAY_0300)


def test_to_jkia_at_a_knot_is_the_rf_prediction(travel):
    # 4.5 h after Tuesday 03:00 is Tuesday 07:30, the knot of hour 7: zone A,
    # Tuesday (1), hour 7.
    assert travel(ZONES["A"], JKIA, 4.5 * 3600) == 1000 + 100 + 7


@pytest.mark.parametrize("seed", range(3))
def test_to_jkia_interpolates_as_the_validation_does(travel, seed):
    rng = random.Random(seed)
    g = grid()
    for _ in range(200):
        depart = rng.uniform(-3 * 3600, 8 * 24 * 3600)  # past Sunday into next week
        hours = 3 + 24 + depart / 3600  # Monday 00:00 + Tuesday 03:00 + depart
        assert travel(ZONES["C"], JKIA, depart) == pytest.approx(
            g.seconds("C", 0, hours % 168), abs=1e-9
        )


def test_between_zones_is_exactly_the_zone_matrix(travel, matrix):
    rng = random.Random(1)
    for _ in range(300):
        depart = rng.uniform(0, 7 * 24 * 3600)
        week_hour = 24 + 3 + depart / 3600
        day, hour = divmod(week_hour % 168, 24)
        assert travel(ZONES["A"], ZONES["B"], depart) == pytest.approx(
            matrix.leg("A", "B", int(day), hour), abs=1e-9
        )


def test_within_a_zone_is_the_same_zone_rule(travel, matrix):
    near_a = Point(-1.31, 36.80)  # about 1.1 km south of A's point
    km = travel_time.haversine_km(ZONES["A"], near_a)
    rng = random.Random(2)
    for _ in range(100):
        depart = rng.uniform(0, 7 * 24 * 3600)
        day, hour = divmod((24 + 3 + depart / 3600) % 168, 24)
        assert travel(ZONES["A"], near_a, depart) == pytest.approx(
            matrix.same_zone("A", km, int(day), hour), abs=1e-9
        )


def test_points_snap_to_the_nearest_zone(travel):
    # Closer to B's point than to A's or C's: it travels as B.
    near_b = Point(-1.29, 36.89)
    assert travel_time.nearest_zone(near_b, ZONES)[0] == "B"
    assert travel(near_b, JKIA, 4.5 * 3600) == travel(ZONES["B"], JKIA, 4.5 * 3600)
    assert travel(ZONES["A"], near_b, 3600) == travel(ZONES["A"], ZONES["B"], 3600)
    zone, km = travel_time.nearest_zone(near_b, ZONES)
    assert km == pytest.approx(travel_time.haversine_km(near_b, ZONES["B"]))


def test_each_function_keeps_its_own_cache(tmp_path, matrix):
    (tmp_path / "other").mkdir()
    other = zone_matrix.load(*write_files(tmp_path / "other", l2=zone_matrix_fixture_slower()))
    first = travel_time.rf_travel_time(grid(), matrix, ZONES, TUESDAY_0300)
    second = travel_time.rf_travel_time(grid(500), other, ZONES, TUESDAY_0300)
    ten_hours = 10 * 3600  # Tuesday 13:00

    # The first function's answers, cached, must not leak into the second's.
    assert first(ZONES["A"], ZONES["B"], ten_hours) == pytest.approx(matrix.leg("A", "B", 1, 13))
    assert second(ZONES["A"], ZONES["B"], ten_hours) == pytest.approx(other.leg("A", "B", 1, 13))
    assert first(ZONES["A"], ZONES["B"], ten_hours) != second(ZONES["A"], ZONES["B"], ten_hours)
    assert first(ZONES["A"], JKIA, ten_hours) + 500 == second(ZONES["A"], JKIA, ten_hours)


def zone_matrix_fixture_slower():
    # Layer 2 with A's early hours busier, so c (and the A-B leg) differs.
    return {"A": {5: 1300, 18: 1600}, "B": {5: 500, 18: 700}, "C": {5: 800, 18: 900}}


def test_it_depends_on_departure_and_asks_for_detour_ranking(travel):
    assert not hasattr(travel, "ignores_departure_time")
    assert travel.ranks_detours_at_start


def test_mismatched_zones_are_refused(matrix):
    with pytest.raises(ValueError, match="same zones"):
        travel_time.rf_travel_time(grid(), matrix, {"A": ZONES["A"]}, TUESDAY_0300)


def test_problem_ranks_detours_by_the_legs_at_time_0(travel, monkeypatch):
    places = [Point(-1.30, 36.80 + 0.01 * k) for k in range(1, 6)] + [Point(-1.25, 36.86)]
    problem = Problem(
        tuple(insertion_pickup(f"p{k}", p) for k, p in enumerate(places)),
        (smoke_30().vehicles[0],),
        travel,
    )

    assert problem.legs is None
    detours = problem.detour_legs
    assert detours.between[0][5] == travel(places[0], places[5], 0.0)
    assert detours.from_start[0][detours.destination] == travel(
        problem.vehicles[0].start, JKIA, 0.0
    )

    # Two of the five positions by default, as chosen in #109...
    shortlist = insertion._positions_worth_costing(problem, [0, 1, 2, 3], 0, 4)
    assert len(shortlist) == 2 and set(shortlist) <= {0, 1, 2, 3, 4}
    # ...every position with None...
    monkeypatch.setattr(insertion, "TIME_DEPENDENT_FULLY_COSTED_POSITIONS", None)
    assert insertion._positions_worth_costing(problem, [0, 1, 2, 3], 0, 4) == [0, 1, 2, 3, 4]
    # ...and a shortlist of its own size, not FULLY_COSTED_POSITIONS's.
    monkeypatch.setattr(insertion, "FULLY_COSTED_POSITIONS", 1)
    monkeypatch.setattr(insertion, "TIME_DEPENDENT_FULLY_COSTED_POSITIONS", 3)
    assert len(insertion._positions_worth_costing(problem, [0, 1, 2, 3], 0, 4)) == 3


def insertion_pickup(pickup_id, location):
    return Pickup(pickup_id, location, deadline=6 * 3600, service_sec=60)


def test_without_the_marker_every_position_is_costed():
    def plain(origin, dest, depart_sec):
        return 600.0 + depart_sec / 1000

    problem = Problem(
        tuple(insertion_pickup(f"p{k}", Point(-1.3, 36.8 + 0.01 * k)) for k in range(5)),
        (smoke_30().vehicles[0],),
        plain,
    )
    assert problem.detour_legs is None
    assert insertion._positions_worth_costing(problem, [0, 1, 2, 3], 0, 4) == [0, 1, 2, 3, 4]


NEAR_A = Point(-1.31, 36.80)  # same zone as A
ON_JKIA = Point(JKIA.lat, JKIA.lon)  # equal to JKIA, another object


def test_leg_functions_are_exactly_travel_time(travel, matrix):
    # Every kind of leg (to JKIA, between zones, within a zone, from JKIA,
    # to a pickup sitting on JKIA), at 300 times across the week: the very
    # same float, not just close (#109).
    places = [ZONES["A"], ZONES["B"], ZONES["C"], NEAR_A, JKIA, ON_JKIA]
    rng = random.Random(7)
    departs = [rng.uniform(-3 * 3600, 8 * 24 * 3600) for _ in range(300)]
    for origin in places:
        for dest in places:
            if origin is dest:
                continue
            leg = travel.leg_function(origin, dest)
            for depart in departs:
                assert leg(depart) == travel(origin, dest, depart), (origin, dest, depart)

    # The times reach both sides of the morning anchor and #105's line
    # outside [0, 1] (below 0 here: the fixture's Layer 2 never passes its
    # 18:00 peak), so every branch of leg_at was compared.
    cs = [matrix.congestion("A", "B", *divmod((27 + t / 3600) % 168, 24)) for t in departs]
    c_m = matrix.morning_congestion("A", "B")
    assert any(c < 0 for c in cs)
    assert any(0 <= c <= c_m for c in cs) and any(c_m < c <= 1 for c in cs)


def test_a_pickup_on_jkia_is_a_leg_to_jkia(travel):
    # Equal to the destination, so the RF leg, as travel_time decides it.
    assert travel.leg_function(ZONES["A"], ON_JKIA)(3600) == travel(ZONES["A"], JKIA, 3600)


def test_problem_times_routes_by_its_leg_functions(travel):
    places = [ZONES["B"], NEAR_A, ZONES["C"], ON_JKIA]
    vehicles = (
        Vehicle("v0", 14, ZONES["A"]),
        Vehicle("v1", 14, Point(-1.21, 36.85), available_from=1800),
    )
    pickups = tuple(insertion_pickup(f"p{k}", p) for k, p in enumerate(places))
    problem = Problem(pickups, vehicles, travel)

    table = problem.timed_legs
    assert len(table.from_start) == len(vehicles)  # a row per vehicle start
    assert table.from_start[1][0](900) == travel(vehicles[1].start, places[0], 900)
    assert table.between[3][table.destination](900) == travel(ON_JKIA, JKIA, 900)

    # Without leg_function the solver calls travel_time with Points; the
    # arrivals must be the same floats either way, from each vehicle.
    def without(origin, dest, depart_sec):
        return travel(origin, dest, depart_sec)

    without.ranks_detours_at_start = True
    by_points = Problem(pickups, vehicles, without)
    assert by_points.timed_legs is None
    for v in range(len(vehicles)):
        for start in (0.0, 4321.5, 20000.0):
            route = [2, 0, 3, 1]
            assert _drive(problem, v, route, start) == _drive(by_points, v, route, start)


def test_route_timing_calls_the_leg_functions_not_travel_time(travel):
    # The point of #109 (b): with leg functions, timing a route never goes
    # back to travel_time with Points (its snapping and lookups).
    calls = []

    def counted(origin, dest, depart_sec):
        calls.append(depart_sec)
        return travel(origin, dest, depart_sec)

    counted.ranks_detours_at_start = True
    counted.leg_function = travel.leg_function
    pickups = tuple(insertion_pickup(f"p{k}", p) for k, p in enumerate([ZONES["B"], NEAR_A]))
    problem = Problem(pickups, (smoke_30().vehicles[0],), counted)
    calls.clear()  # the time-0 table for detour ranking calls it once per leg

    arrivals, end = _drive(problem, 0, [0, 1], 3600.0)

    assert calls == []
    assert end > arrivals[-1] > arrivals[0] > 3600.0


def test_job_api_problems_get_the_leg_functions(travel, matrix, monkeypatch):
    # The job API (#51) builds its Problem in the solver process
    # (worker.build_problem); it must get #109's leg functions like any other.
    monkeypatch.setattr(worker, "_rf_inputs", (grid(), matrix, ZONES))
    epoch = TUESDAY_0300.replace(tzinfo=worker.EAT)
    pickup = worker.PickupInput("p0", ZONES["B"], epoch + timedelta(hours=3))
    job = worker.SolveInput(
        (pickup,), (worker.VehicleInput("v0", 14),), JKIA, epoch, 1.0, "rf", seed=0
    )

    problem = worker.build_problem(job)

    assert problem.timed_legs is not None
    # The worker's RF is the one from these inputs at this epoch.
    assert problem.timed_legs.from_start[0][0](900) == travel(JKIA, ZONES["B"], 900)


def test_no_leg_functions_with_stop_windows_or_without_the_offer(travel):
    windowed = Pickup("w", ZONES["B"], deadline=6 * 3600, ready=0.0, due=3600.0)
    problem = Problem((windowed,), (smoke_30().vehicles[0],), travel, weights=SOLOMON)
    assert problem.timed_legs is None
    assert smoke_30().timed_legs is None  # haversine has its table of legs instead


@pytest.fixture(scope="module")
def real_travel():
    model = journey_time.train()
    return travel_time.rf_travel_time(
        journey_time.predict_grid(model),
        zone_matrix.load(),
        travel_time.load_zone_points(),
        datetime(2026, 10, 28, 3, 0),
    )


def test_real_travel_is_fifo_all_week(real_travel):
    # Leaving later never arrives earlier: t + f(t) never falls, for every
    # zone to JKIA and every pair of zones, at 15-minute steps over the week.
    zones = list(travel_time.load_zone_points().values())
    pairs = [(z, JKIA) for z in zones] + [(a, b) for a in zones for b in zones if a is not b]
    steps = [k * 900.0 for k in range(7 * 96 + 1)]
    for origin, dest in pairs:
        arrivals = [t + real_travel(origin, dest, t) for t in steps]
        assert all(b >= a for a, b in zip(arrivals, arrivals[1:], strict=False)), (origin, dest)


def test_a_solve_with_rf_travel_is_feasible(real_travel):
    crew = smoke_30()
    problem = Problem(crew.pickups, crew.vehicles, real_travel)

    result = solve(problem, random.Random(1), max_generations=3, clock=lambda: 0.0)

    assert_feasible(problem, result.best)


def test_leg_functions_change_no_solve(real_travel):
    # The same plan to the last bit, with or without the leg functions.
    def without(origin, dest, depart_sec):
        return real_travel(origin, dest, depart_sec)

    without.ranks_detours_at_start = True
    crew = smoke_30()
    results = [
        solve(Problem(crew.pickups, crew.vehicles, t), random.Random(2), max_generations=2,
              clock=lambda: 0.0)
        for t in (real_travel, without)
    ]  # fmt: skip
    assert repr(results[0].evaluation.cost) == repr(results[1].evaluation.cost)
    assert results[0].best == results[1].best
