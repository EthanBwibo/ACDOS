"""Order crossover (OX1, Davis 1985) on the giant tour: the GA's recombination.

As in Prins (2004), the GA crosses giant tours and splits the child into
routes: both parents become giant tours (routes end to end, unassigned last),
the child tour takes a slice of parent A and the rest in parent B's order, and
split() turns it back into routes. Prins's Split is optimal (a shortest path);
split() here is greedy, in tour order, with the deadline and lost-cause rules. The child keeps a run of A's visiting
order and B's sense of who comes before whom, without ever visiting a pickup
twice or missing one.
"""

import random

from app.solver.individual import Individual, split
from app.solver.problem import Problem


def ox1(tour_a: list[int], tour_b: list[int], start: int, end: int) -> list[int]:
    """The OX1 child of two tours with the slice [start, end) taken from A.

    A's slice keeps its positions. The other positions, from end to the last
    and then from 0 to start - 1, are filled with B's pickups in B's order,
    reading B from end onwards and wrapping round, skipping any already in
    the slice.
    """
    n = len(tour_a)
    child: list[int] = [-1] * n
    child[start:end] = tour_a[start:end]
    in_slice = set(tour_a[start:end])
    from_b = [i for i in tour_b[end:] + tour_b[:end] if i not in in_slice]
    positions = list(range(end, n)) + list(range(start))
    for position, i in zip(positions, from_b, strict=True):
        child[position] = i
    return child


def order_crossover(
    problem: Problem, parent_a: Individual, parent_b: Individual, rng: random.Random
) -> Individual:
    """One child of A and B; the parents are not changed.

    The slice is drawn uniformly among non-empty slices of A's tour. Pickups
    the fleet cannot take come out of split() in unassigned, as for any tour.
    """
    tour_a, tour_b = parent_a.giant_tour(), parent_b.giant_tour()
    if len(tour_a) < 2:
        return split(problem, tour_a)  # nothing to cross
    start, end = sorted(rng.sample(range(len(tour_a) + 1), 2))
    return split(problem, ox1(tour_a, tour_b, start, end))
