"""The GA's initial population, and the duplicate check the GA loop (#74) shares.

Most of the population is random giant tours passed through split(): random
for diversity, split() so every individual respects capacity and places lost
causes sensibly. The caller adds seeds, such as the nearest-neighbour
solution (#73), so the search starts from at least one sensible solution.
"""

import random

from app.solver.individual import Individual, split
from app.solver.problem import Problem

# Random tours tried per individual wanted. On a tiny instance there can be
# fewer distinct solutions than the population size; the cap stops the search
# for more instead of looping forever.
SHUFFLE_ATTEMPTS_PER_INDIVIDUAL = 10

StructureKey = tuple[tuple[tuple[tuple[int, ...], ...], ...], tuple[int, ...]]


def structure_key(problem: Problem, individual: Individual) -> StructureKey:
    """A hashable key that is equal exactly when two solutions are the same plan.

    Vehicles with the same start, capacity and available_from are
    interchangeable: swapping their routes changes nothing a dispatcher would
    see, and the cost is the same. So their routes are sorted within the key,
    and two plans that differ only by such a swap get the same key. The order
    of stops within a route matters; the order of unassigned does not.

    Equal keys mean equal cost, so no separate cost comparison is needed.
    """
    groups: dict[tuple, list[tuple[int, ...]]] = {}
    for vehicle, route in zip(problem.vehicles, individual.routes, strict=True):
        alike = (vehicle.start, vehicle.capacity, vehicle.available_from)
        groups.setdefault(alike, []).append(tuple(route))
    # dicts keep insertion order, so groups come in order of their first vehicle.
    routes = tuple(tuple(sorted(group)) for group in groups.values())
    return routes, tuple(sorted(individual.unassigned))


def initial_population(
    problem: Problem,
    size: int,
    rng: random.Random,
    seeds: tuple[Individual, ...] = (),
) -> list[Individual]:
    """Up to size distinct individuals: the seeds first, then random tours.

    Returns fewer than size when the random tours run out of new solutions
    within SHUFFLE_ATTEMPTS_PER_INDIVIDUAL * size tries (only on tiny
    instances in practice). A seed that duplicates an earlier one is skipped.
    """
    population: list[Individual] = []
    seen: set[StructureKey] = set()

    def add(individual: Individual) -> None:
        key = structure_key(problem, individual)
        if key not in seen:
            seen.add(key)
            population.append(individual)

    for seed in seeds:
        if len(population) < size:
            add(seed)

    tour = list(range(len(problem.pickups)))
    for _ in range(SHUFFLE_ATTEMPTS_PER_INDIVIDUAL * size):
        if len(population) >= size:
            break
        rng.shuffle(tour)
        add(split(problem, tour))

    return population
