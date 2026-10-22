"""Nearest-neighbour construction heuristic: the baseline the GA-ALNS is
compared against in the results chapter, and one individual in the GA's
initial population (#8).

Route by route, for vehicles in index order:
- Start with the unrouted pickup that has the earliest report time (the most
  urgent), as in Solomon's (1987) time-oriented nearest neighbour. Plain
  nearest-first, ignoring report times, would be a strawman baseline for a
  problem driven by deadlines.
- Then keep adding the nearest unrouted pickup, by travel time from where the
  vehicle is at the time it leaves there (so it uses the Random Forest once
  #23 lands), skipping any that would overfill the vehicle or make someone
  on board late.
- Close the route when nothing fits, and move to the next vehicle.

Lost causes (late even alone on every vehicle) are left out of that and
placed at the end, by the same rule as split(): they join an open route
without using up a vehicle of their own.
"""

from app.solver.individual import Individual, RouteBuilder, late_even_alone
from app.solver.problem import Problem


def nearest_neighbour(problem: Problem) -> Individual:
    """Build one solution; deterministic, ties to the lowest pickup index.

    Pickups the fleet cannot take go to unassigned, in report-time order.
    """
    pickups = problem.pickups
    builder = RouteBuilder(problem)
    by_report_time = sorted(range(len(pickups)), key=lambda i: (pickups[i].deadline, i))
    lost_causes = [i for i in by_report_time if late_even_alone(problem, pickups[i])]
    unrouted = [i for i in by_report_time if i not in lost_causes]

    for w in range(len(problem.vehicles)):
        if not unrouted:
            break
        # Seed: the most urgent pickup that fits in this vehicle at all.
        seed = _first_that_fits(builder, w, unrouted)
        if seed is None:
            continue
        unrouted.remove(seed)
        while unrouted:
            position, clock = builder.position_and_clock(w)
            nearest_first = sorted(
                unrouted,
                key=lambda i: (problem.travel_time(position, pickups[i].location, clock), i),
            )
            nearest = _first_that_fits(builder, w, nearest_first)
            if nearest is None:
                break
            unrouted.remove(nearest)

    unassigned = unrouted
    for i in lost_causes:
        if builder.join_least_late_route(i):
            continue
        # No open route has room: open an unused vehicle, as split() would.
        unused = [w for w, route in enumerate(builder.routes) if not route]
        if not any(builder.try_append(w, i) for w in unused):
            unassigned.append(i)

    return Individual(builder.routes, unassigned)


def _first_that_fits(builder: RouteBuilder, w: int, candidates: list[int]) -> int | None:
    """Append the first candidate vehicle w can take, and return it."""
    for i in candidates:
        if builder.try_append(w, i):
            return i
    return None
