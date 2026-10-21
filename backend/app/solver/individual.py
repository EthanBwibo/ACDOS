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
# Bisection halves the interval each step, so a day-long interval needs about
# 11 steps to reach 60 s. The cap only guards against a broken bound (NaN).
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
    problem: Problem, vehicle: Vehicle, route: list[int], start: float
) -> tuple[list[float], float]:
    """Arrival at each stop, and at the destination, leaving at start."""
    partial = _Partial(0, start, vehicle.start, math.inf)
    arrivals = []
    for i in route:
        partial = _add(problem, partial, problem.pickups[i])
        # _add moved the clock to departure; arrival is before boarding.
        arrivals.append(partial.clock - problem.pickups[i].service_sec)
    return arrivals, _destination_arrival(problem, partial)


def _latest_start(problem: Problem, vehicle: Vehicle, route: list[int], buffer_sec: float) -> float:
    """Latest start that has everyone at the destination buffer_sec before the
    earliest report time on board, never before available_from.

    Found by bisection on [available_from, earliest report time], because the
    drive times change with the start once travel time depends on departure
    time. lo is always a start known to arrive in time, so the answer is never
    late. If travel time is not FIFO (leaving later can arrive earlier), the
    answer may not be the latest such start, but it still arrives in time.
    An RF predicting by whole hour is not FIFO at hour boundaries, which is why
    #23 interpolates between hours.
    """
    report = min(problem.pickups[i].deadline for i in route)
    target = report - buffer_sec
    lo = vehicle.available_from
    # No report time to work back from, or the target is out of reach even
    # leaving now (a lost cause on board, or on time only inside the buffer):
    # leave as early as possible.
    if math.isinf(target) or _drive(problem, vehicle, route, lo)[1] > target:
        return lo

    hi = report
    for _ in range(MAX_DEPARTURE_SEARCH_STEPS):
        if hi - lo <= DEPARTURE_TOLERANCE_SEC:
            break
        mid = (lo + hi) / 2
        if _drive(problem, vehicle, route, mid)[1] <= target:
            lo = mid
        else:
            hi = mid
    return lo


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

    vehicle = problem.vehicles[vehicle_index]
    if latest_departure:
        start = _latest_start(problem, vehicle, route, buffer_sec)
    else:
        start = vehicle.available_from
    arrivals, end = _drive(problem, vehicle, route, start)
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
    up a vehicle of its own, so it joins an open route with room: preferably
    one where it makes no on-time pickup late, and among those the one where it
    adds the least lateness (its own plus other lost causes it delays). Only if
    every open route would make someone late does it take the least total
    lateness regardless. Lowest vehicle index on a tie. Only if no open route
    has room does it move on to the next vehicle. Its lateness is reported
    through Stop.lateness like any other.
    """
    vehicles = problem.vehicles
    routes: list[list[int]] = [[] for _ in vehicles]
    # partials[w] is the state of vehicle w's route, set once it has a stop.
    partials: list[_Partial | None] = [None] * len(vehicles)
    unassigned: list[int] = []
    v = 0  # the vehicle being filled

    for i in tour:
        if v < len(vehicles) and _try_append(problem, routes, partials, v, i):
            continue
        if _late_even_alone(problem, problem.pickups[i]):
            w = _least_late_open_route(problem, routes, partials, i)
            if w is not None:
                partials[w] = _add(problem, partials[w], problem.pickups[i], track_deadline=False)
                routes[w].append(i)
                continue
        # Move on: this vehicle's route is closed for the rest of the tour.
        v += 1
        while v < len(vehicles) and not _try_append(problem, routes, partials, v, i):
            v += 1
        if v >= len(vehicles):
            unassigned.append(i)

    return Individual(routes, unassigned)


def _try_append(
    problem: Problem, routes: list[list[int]], partials: list[_Partial | None], w: int, i: int
) -> bool:
    """Add pickup i to the end of vehicle w's route if that keeps it valid."""
    vehicle = problem.vehicles[w]
    pickup = problem.pickups[i]
    partial = partials[w] if partials[w] is not None else _start(vehicle)
    candidate = _add(problem, partial, pickup)
    if candidate.load > vehicle.capacity:
        return False
    if _destination_arrival(problem, candidate) > candidate.earliest_deadline:
        if routes[w]:
            return False
        # First stop and late even so: accept it, but leave its deadline out
        # so it does not turn away every pickup after it.
        candidate = _add(problem, partial, pickup, track_deadline=False)
    partials[w] = candidate
    routes[w].append(i)
    return True


def _late_even_alone(problem: Problem, pickup: Pickup) -> bool:
    for vehicle in problem.vehicles:
        alone = _add(problem, _start(vehicle), pickup)
        if _destination_arrival(problem, alone) <= pickup.deadline:
            return False
    return True


def _least_late_open_route(
    problem: Problem, routes: list[list[int]], partials: list[_Partial | None], i: int
) -> int | None:
    """Open route with room for lost cause i: one where it makes no on-time
    pickup late if any, then the least total lateness added."""
    # Tuples compare element by element: False (nobody made late) sorts first.
    best, best_key = None, (True, math.inf)
    for w, route in enumerate(routes):
        if not route:
            continue
        candidate = _add(problem, partials[w], problem.pickups[i], track_deadline=False)
        if candidate.load > problem.vehicles[w].capacity:
            continue
        end_before = _destination_arrival(problem, partials[w])
        end_after = _destination_arrival(problem, candidate)
        makes_someone_late = any(
            end_before <= problem.pickups[j].deadline < end_after for j in route
        )
        added = _total_lateness(problem, [*route, i], end_after) - _total_lateness(
            problem, route, end_before
        )
        if (makes_someone_late, added) < best_key:
            best, best_key = w, (makes_someone_late, added)
    return best


def _total_lateness(problem: Problem, route: list[int], end: float) -> float:
    return sum(max(0.0, end - problem.pickups[j].deadline) for j in route)
