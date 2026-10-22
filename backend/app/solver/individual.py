"""Chromosome for the GA: one route per vehicle, plus pickups left unserved.

Two views of the same solution:
- routes: what Shaw removal and greedy re-insertion (#10, #11) edit, and
  what gets saved as routes and route_nodes.
- giant tour: every pickup in one sequence, routes joined end to end. Order
  crossover (#9) works on this; split() turns a child tour back into routes.

Pickups and vehicles are referred to by their index in Problem.pickups and
Problem.vehicles, not by id, so the GA loop handles plain ints.
"""

import math
from dataclasses import dataclass, field

from app.solver.problem import Pickup, Point, Problem, Vehicle

# Latest departure aims to have everyone at JKIA this long before the earliest
# report time on board, as slack for traffic the travel time function missed.
REPORT_BUFFER_SEC = 900.0
# The departure search stops once the latest start is known to within this.
DEPARTURE_TOLERANCE_SEC = 60.0
# The departure search (_latest_start) settles in one step when travel time does
# not depend on departure, and in a few otherwise. The cap bounds it when travel
# times keep shifting, or a bound is broken (NaN).
MAX_DEPARTURE_SEARCH_STEPS = 20


@dataclass
class Individual:
    # routes[v] is the visiting order of vehicle v; an empty list means the
    # vehicle is not used. Every route ends at Problem.destination.
    routes: list[list[int]]
    # Pickups no route could take (fleet full). Reported, never dropped
    # silently.
    unassigned: list[int] = field(default_factory=list)

    def copy(self) -> "Individual":
        return Individual([route.copy() for route in self.routes], self.unassigned.copy())

    def giant_tour(self) -> list[int]:
        """All pickups in route order, unassigned last so split() retries them."""
        return [i for route in self.routes for i in route] + self.unassigned


@dataclass(frozen=True)
class Stop:
    pickup_index: int
    arrival: float
    departure: float
    # Seconds past the pickup's deadline at the destination; 0 when on time.
    lateness: float


@dataclass(frozen=True)
class RouteSchedule:
    vehicle_index: int
    stops: tuple[Stop, ...]
    load: int
    # When the vehicle leaves Vehicle.start. None when the vehicle is not used.
    start: float | None
    # None when the vehicle is not used.
    destination_arrival: float | None


@dataclass(frozen=True)
class _Partial:
    """A route built up to its last stop, enough to extend it by one pickup."""

    load: int
    clock: float  # when the vehicle leaves its last stop
    position: Point
    # Earliest deadline among the pickups split() keeps on time. Pickups
    # already late are left out, or they would block every later stop.
    earliest_deadline: float


def _start(vehicle: Vehicle) -> _Partial:
    return _Partial(0, vehicle.available_from, vehicle.start, math.inf)


def _add(
    problem: Problem, partial: _Partial, pickup: Pickup, track_deadline: bool = True
) -> _Partial:
    drive = problem.travel_time(partial.position, pickup.location, partial.clock)
    arrival = partial.clock + drive
    deadline = min(partial.earliest_deadline, pickup.deadline)
    return _Partial(
        load=partial.load + pickup.demand,
        clock=arrival + pickup.service_sec,
        position=pickup.location,
        earliest_deadline=deadline if track_deadline else partial.earliest_deadline,
    )


def _destination_arrival(problem: Problem, partial: _Partial) -> float:
    return partial.clock + problem.travel_time(partial.position, problem.destination, partial.clock)


def _drive(
    problem: Problem, vehicle_index: int, route: list[int], start: float
) -> tuple[list[float], float]:
    """Arrival at each stop, and at the destination, leaving at start.

    A plain loop rather than _add: it runs millions of times per solve, and
    building a _Partial for every stop cost as much as the driving (#85).
    When travel time ignores departure, the legs come from Problem.legs, a
    table built once, instead of a call per leg (#88).
    """
    pickups = problem.pickups
    arrivals = []
    clock = start
    legs = problem.legs
    if legs is not None:
        row = legs.from_start[vehicle_index]
        for i in route:
            arrival = clock + row[i]
            arrivals.append(arrival)
            clock = arrival + pickups[i].service_sec
            row = legs.between[i]
        return arrivals, clock + row[legs.destination]

    travel_time = problem.travel_time
    position = problem.vehicles[vehicle_index].start
    for i in route:
        pickup = pickups[i]
        arrival = clock + travel_time(position, pickup.location, clock)
        arrivals.append(arrival)
        clock = arrival + pickup.service_sec
        position = pickup.location
    return arrivals, clock + travel_time(position, problem.destination, clock)


def _latest_start(
    problem: Problem, vehicle_index: int, route: list[int], buffer_sec: float
) -> float:
    """Latest start that has everyone at the destination buffer_sec before the
    earliest report time on board, never before available_from.

    The drive times change with the start once travel time depends on
    departure time, so the start is searched for, between lo (a start known to
    arrive in time, from available_from) and hi (one known to be late, from
    the report time). Each step tries the start that would arrive exactly on
    target if the drive took as long as the last one did. When travel time does
    not depend on departure that is exact, and the search ends after one step
    (#85). Otherwise each try narrows [lo, hi], and a guess outside it falls
    back to the midpoint, as plain bisection would.

    Only lo is ever returned, so the answer is never late. If travel time is
    not FIFO (leaving later can arrive earlier), the answer may not be the
    latest such start, but it still arrives in time. An RF predicting by whole
    hour is not FIFO at hour boundaries, which is why #23 interpolates between
    hours.
    """
    report = min(problem.pickups[i].deadline for i in route)
    target = report - buffer_sec
    lo = problem.vehicles[vehicle_index].available_from
    if math.isinf(target):
        return lo  # no report time to work back from
    end_lo = _drive(problem, vehicle_index, route, lo)[1]
    if end_lo > target:
        # Out of reach even leaving now (a lost cause on board, or on time only
        # inside the buffer): leave as early as possible.
        return lo

    hi = report
    guess = lo + (target - end_lo)
    for _ in range(MAX_DEPARTURE_SEARCH_STEPS):
        if target - end_lo <= DEPARTURE_TOLERANCE_SEC or hi - lo <= DEPARTURE_TOLERANCE_SEC:
            break
        start = guess if lo < guess < hi else (lo + hi) / 2
        end = _drive(problem, vehicle_index, route, start)[1]
        if end <= target:
            lo, end_lo = start, end
        else:
            hi = start
        guess = start + (target - end)
    return lo


def route_times(
    problem: Problem, vehicle_index: int, route: list[int], buffer_sec: float = REPORT_BUFFER_SEC
) -> tuple[float, list[float], float]:
    """When a non-empty route leaves (latest departure), reaches each stop and
    reaches the destination; all route_evaluation needs, without building
    Stops."""
    start = _latest_start(problem, vehicle_index, route, buffer_sec)
    arrivals, end = _drive(problem, vehicle_index, route, start)
    return start, arrivals, end


def schedule_route(
    problem: Problem,
    vehicle_index: int,
    route: list[int],
    latest_departure: bool = True,
    buffer_sec: float = REPORT_BUFFER_SEC,
) -> RouteSchedule:
    """Times for one route.

    By default the vehicle leaves as late as it can (see _latest_start), so
    crew are not collected hours early to wait at JKIA. latest_departure=False
    leaves at available_from instead. Either way lateness is the same: the
    start only moves later when the route then still arrives in time.

    Everyone on board arrives at the destination together, so a pickup is late
    when that shared arrival is after its deadline, not when it is collected.
    """
    if not route:
        return RouteSchedule(vehicle_index, (), 0, None, None)

    if latest_departure:
        start = _latest_start(problem, vehicle_index, route, buffer_sec)
    else:
        start = problem.vehicles[vehicle_index].available_from
    arrivals, end = _drive(problem, vehicle_index, route, start)
    stops = tuple(
        Stop(
            pickup_index=i,
            arrival=arrival,
            departure=arrival + problem.pickups[i].service_sec,
            lateness=max(0.0, end - problem.pickups[i].deadline),
        )
        for i, arrival in zip(route, arrivals, strict=True)
    )
    load = sum(problem.pickups[i].demand for i in route)
    return RouteSchedule(vehicle_index, stops, load, start, end)


def schedule(
    problem: Problem,
    individual: Individual,
    latest_departure: bool = True,
    buffer_sec: float = REPORT_BUFFER_SEC,
) -> list[RouteSchedule]:
    return [
        schedule_route(problem, v, route, latest_departure, buffer_sec)
        for v, route in enumerate(individual.routes)
    ]


def split(problem: Problem, tour: list[int]) -> Individual:
    """Cut a giant tour into routes; each route visits in tour order.

    Greedy: fill vehicles in order. Move to the next vehicle when the next
    pickup would overfill this one or make anyone on it late. When the fleet
    runs out, the rest of the tour goes to unassigned.

    Lost causes: a pickup that would be late even driven alone by any vehicle
    (its report time is too soon for the fleet to reach JKIA). It must not use
    up a vehicle of its own, so it joins an open route with room (see
    RouteBuilder.join_least_late_route). Only if no open route has room does
    it move on to the next vehicle. Its lateness is reported through
    Stop.lateness like any other.
    """
    vehicles = problem.vehicles
    builder = RouteBuilder(problem)
    unassigned: list[int] = []
    v = 0  # the vehicle being filled

    for i in tour:
        if v < len(vehicles) and builder.try_append(v, i):
            continue
        if late_even_alone(problem, problem.pickups[i]) and builder.join_least_late_route(i):
            continue
        # Move on: this vehicle's route is closed for the rest of the tour.
        v += 1
        while v < len(vehicles) and not builder.try_append(v, i):
            v += 1
        if v >= len(vehicles):
            unassigned.append(i)

    return Individual(builder.routes, unassigned)


class RouteBuilder:
    """Routes built one stop at a time, as split() and the nearest-neighbour
    heuristic build them.

    For each vehicle it keeps the route so far and enough state (a _Partial)
    to check whether one more pickup still fits, without re-timing the route.
    Times assume the vehicle leaves at available_from; that is enough to tell
    who is late, since leaving later never changes that (schedule_route).
    """

    def __init__(self, problem: Problem) -> None:
        self.problem = problem
        self.routes: list[list[int]] = [[] for _ in problem.vehicles]
        # _partials[w] is the state of vehicle w's route, set once it has a stop.
        self._partials: list[_Partial | None] = [None] * len(problem.vehicles)

    def position_and_clock(self, w: int) -> tuple[Point, float]:
        """Where vehicle w is, and when it leaves there, after its last stop."""
        partial = self._partials[w] or _start(self.problem.vehicles[w])
        return partial.position, partial.clock

    def try_append(self, w: int, i: int) -> bool:
        """Add pickup i to the end of vehicle w's route if that keeps it valid."""
        problem = self.problem
        vehicle = problem.vehicles[w]
        pickup = problem.pickups[i]
        partial = self._partials[w] or _start(vehicle)
        candidate = _add(problem, partial, pickup)
        if candidate.load > vehicle.capacity:
            return False
        if _destination_arrival(problem, candidate) > candidate.earliest_deadline:
            if self.routes[w]:
                return False
            # First stop and late even so: accept it, but leave its deadline
            # out so it does not turn away every pickup after it.
            candidate = _add(problem, partial, pickup, track_deadline=False)
        self._partials[w] = candidate
        self.routes[w].append(i)
        return True

    def join_least_late_route(self, i: int) -> bool:
        """Add lost cause i to the end of the best open route with room.

        Preferably one where it makes no on-time pickup late, and among those
        the one where it adds the least lateness (its own plus other lost
        causes it delays). Only if every open route would make someone late
        does it take the least total lateness regardless. Lowest vehicle index
        on a tie. False if no open route has room.
        """
        problem = self.problem
        pickup = problem.pickups[i]
        # Tuples compare element by element: False (nobody made late) sorts first.
        best, best_key = None, (True, math.inf)
        for w, route in enumerate(self.routes):
            if not route:
                continue
            candidate = _add(problem, self._partials[w], pickup, track_deadline=False)
            if candidate.load > problem.vehicles[w].capacity:
                continue
            end_before = _destination_arrival(problem, self._partials[w])
            end_after = _destination_arrival(problem, candidate)
            makes_someone_late = any(
                end_before <= problem.pickups[j].deadline < end_after for j in route
            )
            added = _total_lateness(problem, [*route, i], end_after) - _total_lateness(
                problem, route, end_before
            )
            if (makes_someone_late, added) < best_key:
                best, best_key = w, (makes_someone_late, added)
        if best is None:
            return False
        self._partials[best] = _add(problem, self._partials[best], pickup, track_deadline=False)
        self.routes[best].append(i)
        return True


def late_even_alone(problem: Problem, pickup: Pickup) -> bool:
    """True if no vehicle could get this pickup to the destination on time,
    even driving it alone: a lost cause."""
    for vehicle in problem.vehicles:
        alone = _add(problem, _start(vehicle), pickup)
        if _destination_arrival(problem, alone) <= pickup.deadline:
            return False
    return True


def _total_lateness(problem: Problem, route: list[int], end: float) -> float:
    return sum(max(0.0, end - problem.pickups[j].deadline) for j in route)
