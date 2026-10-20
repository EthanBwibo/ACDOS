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


def schedule_route(problem: Problem, vehicle_index: int, route: list[int]) -> RouteSchedule:
    """Times for one route, with the vehicle leaving as early as it can.

    Everyone on board arrives at the destination together, so a pickup is late
    when that shared arrival is after its deadline, not when it is collected.
    """
    if not route:
        return RouteSchedule(vehicle_index, (), 0, None)

    partial = _start(problem.vehicles[vehicle_index])
    arrivals = []
    for i in route:
        partial = _add(problem, partial, problem.pickups[i])
        # _add moved the clock to departure; arrival is before boarding.
        arrivals.append(partial.clock - problem.pickups[i].service_sec)

    end = _destination_arrival(problem, partial)
    stops = tuple(
        Stop(
            pickup_index=i,
            arrival=arrival,
            departure=arrival + problem.pickups[i].service_sec,
            lateness=max(0.0, end - problem.pickups[i].deadline),
        )
        for i, arrival in zip(route, arrivals, strict=True)
    )
    return RouteSchedule(vehicle_index, stops, partial.load, end)


def schedule(problem: Problem, individual: Individual) -> list[RouteSchedule]:
    return [schedule_route(problem, v, route) for v, route in enumerate(individual.routes)]


def split(problem: Problem, tour: list[int]) -> Individual:
    """Cut a giant tour into routes; each route visits in tour order.

    Greedy: fill vehicles in order. Move to the next vehicle when the next
    pickup would overfill this one or make anyone on it late. When the fleet
    runs out, the rest of the tour goes to unassigned.

    Lost causes: a pickup that would be late even driven alone by any vehicle
    (its report time is too soon for the fleet to reach JKIA). It must not use
    up a vehicle of its own, so it joins the open route with room where it adds
    the least lateness (its own plus anyone it delays), lowest vehicle index on
    a tie. Only if no open route has room does it move on to the next vehicle.
    Its lateness is reported through Stop.lateness like any other.
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
    """Open route with room where adding pickup i adds the least total lateness."""
    best, best_added = None, math.inf
    for w, route in enumerate(routes):
        if not route:
            continue
        candidate = _add(problem, partials[w], problem.pickups[i], track_deadline=False)
        if candidate.load > problem.vehicles[w].capacity:
            continue
        before = _total_lateness(problem, route, _destination_arrival(problem, partials[w]))
        after = _total_lateness(problem, [*route, i], _destination_arrival(problem, candidate))
        if after - before < best_added:
            best, best_added = w, after - before
    return best


def _total_lateness(problem: Problem, route: list[int], end: float) -> float:
    return sum(max(0.0, end - problem.pickups[j].deadline) for j in route)
