"""Greedy insertion (Ropke and Pisinger, 2006), an ALNS repair operator.

Puts the pickups a destroy operator moved to unassigned back into routes, one
at a time, always taking the cheapest insertion left anywhere: whichever
pickup, route and position adds the least to the fitness (#12, #75).

Departure from Ropke and Pisinger (R&P): they can add random noise to
insertion costs, with the adaptive layer choosing between noisy and plain
versions. Left out here because the GA population and crossover already
supply diversity.

Speed-up (#88): when travel time ignores departure, the positions in a route
are ranked by the extra driving the new stop adds (prev -> i -> next minus
prev -> next, three table look-ups) and only the FULLY_COSTED_POSITIONS
cheapest get the full route costing. The others are never cheaper for the
driving, lateness and waiting terms, which depend on the stop only through
how much longer the route gets; but the ride-time term (#89) also depends on
who rides past the new stop, and a route already arriving late can trade
waiting for lateness, so the cheapest detour is not always the cheapest
position. Hence two positions, measured in #88, not one.

With travel time that depends on departure (the Random Forest, #104), the
ranking uses the legs at time 0 (Problem.detour_legs) while the full costing
uses the real departure times. A detour that is shortest at 03:00 need not
be shortest at 07:00, so this is an approximation: unlike #88's shortlist, it
changes the plan (#104). It is kept because it pays in a fixed time. Measured
in #109 on morning_wave_120 under RF travel, 120 s per run: 2 positions gave
a cheaper plan than costing every position on every clean seed (4 of 4);
the fifth seed, unclean on timing, gave the same order. That was from about
77 generations against 34. At the same number of generations (34) the two
were level (2 cheaper on 4 of 5 seeds, but the mean paired difference was
smaller than its spread), so the gain is the extra generations. 3 positions did not
beat 2 on either measure. Hence TIME_DEPENDENT_FULLY_COSTED_POSITIONS = 2.

With stop windows (Solomon, #99) every position is costed: a vehicle that
waits for a ready time can absorb a detour, so a longer detour is not always
a later route, and the shortlist's premise does not hold.
"""

from app.solver.fitness import RouteCostCache, cached_route_cost
from app.solver.individual import Individual
from app.solver.problem import Problem

# Positions per route that get the full route costing, when travel time
# ignores departure (#88). With 2 (and 3), 3 generations on morning_wave_120
# chose exactly what costing every position chose; with 1 they did not, because
# of the ride-time term. 2 is the faster of the two exact-in-practice settings.
FULLY_COSTED_POSITIONS = 2
# The same when positions are ranked by the legs at time 0 (Problem.detour_legs
# for time-dependent travel, #104); None costs every position. Not exact here:
# it changes the plan. Chosen in #109 by cost in equal time (120 s, seeds
# compared pairwise): 2 beat None on every clean seed and 3 did not beat 2
# (docs/results/109-rf-solver-speed).
TIME_DEPENDENT_FULLY_COSTED_POSITIONS: int | None = 2


def insertion_cost(
    problem: Problem,
    routes: list[list[int]],
    v: int,
    i: int,
    k: int,
    cache: RouteCostCache | None = None,
) -> float | None:
    """Change in route v's cost from putting pickup i at position k.

    None if it would overfill the vehicle. Lateness does not rule a position
    out: its cost does the deciding. The fitness also drops by
    the unassigned weight, since i is no longer unassigned; that part is the same
    for every position, so it is left out here.
    """
    route = routes[v]
    load = sum(problem.pickups[j].demand for j in route) + problem.pickups[i].demand
    if load > problem.vehicles[v].capacity:
        return None
    cache = {} if cache is None else cache
    after = cached_route_cost(problem, v, route[:k] + [i] + route[k:], cache)
    return after - cached_route_cost(problem, v, route, cache)


def _best_position(
    problem: Problem, routes: list[list[int]], v: int, i: int, cache: RouteCostCache
) -> tuple[float, int] | None:
    """Cheapest (cost, position) for pickup i in route v, earliest position on a
    tie, among the positions _positions_worth_costing picks."""
    best = None
    for k in _positions_worth_costing(problem, routes[v], v, i):
        cost = insertion_cost(problem, routes, v, i, k, cache)
        if cost is None:
            return None  # capacity is the same at every position
        if best is None or cost < best[0]:
            best = (cost, k)
    return best


def _positions_worth_costing(problem: Problem, route: list[int], v: int, i: int) -> list[int]:
    """Every position, or with a leg table to rank by and no stop windows only
    the few with the smallest detour (lowest position on a tie), in route
    order: FULLY_COSTED_POSITIONS when the table holds the real legs,
    TIME_DEPENDENT_FULLY_COSTED_POSITIONS (if not None) when it holds the legs
    at time 0."""
    positions = len(route) + 1
    legs = problem.detour_legs
    if legs is None or problem.stop_windows:
        return list(range(positions))
    worth = (
        FULLY_COSTED_POSITIONS if legs is problem.legs else TIME_DEPENDENT_FULLY_COSTED_POSITIONS
    )
    if worth is None or positions <= worth:
        return list(range(positions))
    before = [legs.from_start[v]] + [legs.between[j] for j in route]  # rows of prev stops
    after = route + [legs.destination]
    from_i = legs.between[i]
    detours = sorted(
        (before[k][i] + from_i[after[k]] - before[k][after[k]], k) for k in range(positions)
    )
    return sorted(k for _, k in detours[:worth])


def greedy_insertion(problem: Problem, individual: Individual) -> Individual:
    """Insert unassigned pickups, cheapest first, until none fits.

    Returns a new Individual; the input is not changed. Pickups that fit
    nowhere stay in unassigned in their original order. Ties go to the lowest
    pickup index, then vehicle, then position, so the result is deterministic.
    """
    routes = [route.copy() for route in individual.routes]
    pending = individual.unassigned.copy()
    cache: RouteCostCache = {}
    # best[(i, v)]: cheapest (cost, position) for pickup i in route v, or None.
    best = {
        (i, v): _best_position(problem, routes, v, i, cache)
        for i in pending
        for v in range(len(routes))
    }

    while pending:
        candidates = [
            (position[0], i, v, position[1])
            for (i, v), position in best.items()
            if position is not None
        ]
        if not candidates:
            break
        cost, i, v, k = min(candidates)
        # Inserting must lower the total, which by the tiers it always does
        # when there is room; checked so the rule matches the fitness exactly.
        if cost >= problem.weights.unassigned:
            break

        routes[v].insert(k, i)
        pending.remove(i)
        best = {key: position for key, position in best.items() if key[0] != i}
        # Only route v changed, so only its positions need re-costing.
        for j in pending:
            best[(j, v)] = _best_position(problem, routes, v, j, cache)

    return Individual(routes, pending)
