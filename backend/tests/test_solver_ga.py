import itertools
import math
import random

import pytest

from app.solver.fitness import fitness
from app.solver.ga import (
    Outcome,
    Population,
    StopReason,
    UniformMutation,
    solve,
)
from app.solver.individual import Individual, split
from app.solver.population import structure_key
from app.solver.problem import Pickup, Point, Problem, Vehicle, haversine_travel_time
from tests.solver_checks import assert_feasible

DEPOT = Point(-1.30, 36.80)


def legs_problem(deadlines, capacities):
    """Every leg takes 600 s."""
    pickups = tuple(
        Pickup(f"p{i}", Point(-1.28, 36.81 + i / 100), deadline)
        for i, deadline in enumerate(deadlines)
    )
    vehicles = tuple(Vehicle(f"v{v}", c, DEPOT) for v, c in enumerate(capacities))
    return Problem(pickups, vehicles, lambda origin, dest, depart_sec: 600.0)


def random_problem(seed, n_pickups=12, n_vehicles=4, capacity=4):
    rng = random.Random(seed)
    pickups = tuple(
        Pickup(
            f"p{i}",
            Point(rng.uniform(-1.35, -1.20), rng.uniform(36.70, 36.95)),
            deadline=rng.uniform(1800, 4 * 3600),
            service_sec=60,
        )
        for i in range(n_pickups)
    )
    vehicles = tuple(Vehicle(f"v{v}", capacity, DEPOT) for v in range(n_vehicles))
    return Problem(pickups, vehicles, haversine_travel_time(speed_kmh=30))


def fake_clock(step=0.0):
    """A clock that moves step seconds every time it is read."""
    ticks = itertools.count()
    return lambda: next(ticks) * step


class ScriptedMutation:
    """Returns the given individuals in turn and records the outcomes."""

    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = 0
        self.outcomes = []

    def __call__(self, individual, rng):
        self.calls += 1
        return self.results.pop(0) if self.results else individual

    def record(self, outcome):
        self.outcomes.append(outcome)


# Population: tournament and replacement

# Four crew, two vans: each pair reports 30 min apart, the pairs 3 h apart.
# Every individual below is feasible. From cheapest: each pair in its own van;
# all four in one van (one van, 25,200 s of waiting); pairs mixed (two vans,
# each waiting about 3 h); one crew member left without a vehicle.
PROBLEM = legs_problem([20000, 21800, 30800, 32600], capacities=[4, 4])
PAIRS = Individual([[0, 1], [2, 3]])  # the optimum: each pair shares a van
MIXED = Individual([[0, 2], [1, 3]])
ALL_IN_ONE = Individual([[0, 1, 2, 3], []])
ONE_LEFT_OUT = Individual([[0, 1], [2]], unassigned=[3])


def test_costs_used_below_are_in_the_expected_order():
    costs = [fitness(PROBLEM, i) for i in (PAIRS, ALL_IN_ONE, MIXED, ONE_LEFT_OUT)]

    assert costs == sorted(costs)


def test_tournament_picks_the_cheaper_of_the_two_drawn():
    population = Population(PROBLEM, [ONE_LEFT_OUT, PAIRS])

    for seed in range(20):
        assert population.tournament(random.Random(seed)) == 1


def test_the_second_tournament_leaves_out_the_first_parent():
    population = Population(PROBLEM, [PAIRS, MIXED])

    for seed in range(20):
        assert population.tournament(random.Random(seed), exclude=0) == 1


def test_a_cheaper_new_child_replaces_the_worst():
    population = Population(PROBLEM, [ALL_IN_ONE, ONE_LEFT_OUT])
    cost = fitness(PROBLEM, MIXED)

    outcome = population.offer(MIXED, cost, cost_before_mutation=math.inf)

    assert population.individuals == [ALL_IN_ONE, MIXED]
    assert outcome is Outcome.IMPROVED


def test_a_child_cheaper_than_everyone_is_a_new_best():
    population = Population(PROBLEM, [MIXED, ONE_LEFT_OUT])

    outcome = population.offer(PAIRS, fitness(PROBLEM, PAIRS), cost_before_mutation=0)

    assert population.individuals == [MIXED, PAIRS]
    assert population.best_cost == fitness(PROBLEM, PAIRS)
    assert outcome is Outcome.NEW_BEST


def test_an_accepted_child_no_cheaper_than_before_mutation_scores_if_never_seen():
    population = Population(PROBLEM, [PAIRS, ONE_LEFT_OUT])

    outcome = population.offer(ALL_IN_ONE, fitness(PROBLEM, ALL_IN_ONE), cost_before_mutation=0)

    assert population.individuals == [PAIRS, ALL_IN_ONE]
    assert outcome is Outcome.ACCEPTED_NEW


def test_an_accepted_child_seen_in_an_earlier_generation_scores_nothing():
    population = Population(PROBLEM, [PAIRS, ONE_LEFT_OUT])
    # As if ALL_IN_ONE had been in the population before and been replaced.
    population.seen.add(structure_key(PROBLEM, ALL_IN_ONE))

    outcome = population.offer(ALL_IN_ONE, fitness(PROBLEM, ALL_IN_ONE), cost_before_mutation=0)

    assert population.individuals == [PAIRS, ALL_IN_ONE]
    assert outcome is Outcome.NO_SCORE


def test_a_dearer_child_is_discarded():
    population = Population(PROBLEM, [PAIRS, MIXED])

    outcome = population.offer(ONE_LEFT_OUT, fitness(PROBLEM, ONE_LEFT_OUT), 0)

    assert population.individuals == [PAIRS, MIXED]
    assert outcome is Outcome.NO_SCORE


def test_a_duplicate_child_is_discarded_even_if_cheaper_than_the_worst():
    population = Population(PROBLEM, [PAIRS, ONE_LEFT_OUT])
    # The same plan as PAIRS with the two identical vans swapped.
    swapped = Individual([[2, 3], [0, 1]])

    outcome = population.offer(swapped, fitness(PROBLEM, swapped), math.inf)

    assert population.individuals == [PAIRS, ONE_LEFT_OUT]
    assert outcome is Outcome.NO_SCORE


# solve()


def test_finds_the_hand_checked_optimum():
    # Each pair reports 30 min apart and shares a van; the pairs are 3 h
    # apart, so mixing them makes crew wait hours (#12's exchange rate).
    result = solve(PROBLEM, random.Random(0), max_generations=20, clock=fake_clock())

    assert sorted(sorted(route) for route in result.best.routes) == [[0, 1], [2, 3]]
    assert result.evaluation.cost == fitness(PROBLEM, PAIRS)
    assert assert_feasible(PROBLEM, result.best) == {}


@pytest.mark.parametrize("seed", range(3))
def test_best_cost_never_rises_and_the_population_has_no_duplicates(seed):
    problem = random_problem(seed)

    result = solve(problem, random.Random(seed), max_generations=10, clock=fake_clock())

    best_costs = [stats.best_cost for stats in result.history]
    assert best_costs == sorted(best_costs, reverse=True)
    keys = [structure_key(problem, individual) for individual in result.population]
    assert len(set(keys)) == len(keys)
    assert result.evaluation.cost == best_costs[-1]
    assert_feasible(problem, result.best)


def test_stops_at_the_generation_cap():
    result = solve(
        random_problem(1),
        random.Random(1),
        max_generations=3,
        clock=fake_clock(),
        no_improvement_generations=100,
    )

    assert result.stop_reason is StopReason.MAX_GENERATIONS
    assert result.generations == 3
    assert [stats.generation for stats in result.history] == [1, 2, 3]


def test_stops_at_the_time_limit():
    # Each clock read moves 1 s; the limit is 10 s.
    result = solve(random_problem(1), random.Random(1), time_limit_sec=10, clock=fake_clock(1.0))

    assert result.stop_reason is StopReason.TIME_LIMIT
    assert result.history[-1].elapsed_sec >= 10


def test_stops_when_the_best_has_not_improved_for_long_enough():
    # The optimum is in reach at once (four crew), so the best soon stalls.
    result = solve(
        PROBLEM,
        random.Random(0),
        max_generations=1000,
        no_improvement_generations=5,
        clock=fake_clock(),
    )

    assert result.stop_reason is StopReason.NO_IMPROVEMENT
    assert result.generations < 1000
    tail = [stats.best_cost for stats in result.history[-6:]]
    assert len(set(tail[1:])) == 1


def test_the_same_seed_gives_the_same_run():
    problem = random_problem(2)

    first = solve(problem, random.Random(5), max_generations=5, clock=fake_clock(0.001))
    second = solve(problem, random.Random(5), max_generations=5, clock=fake_clock(0.001))

    assert first == second


def test_mutation_rate_zero_never_mutates():
    mutation = ScriptedMutation()

    solve(
        PROBLEM,
        random.Random(0),
        max_generations=3,
        mutation_rate=0.0,
        mutation=mutation,
        clock=fake_clock(),
    )

    assert mutation.calls == 0
    assert mutation.outcomes == []


def test_every_mutated_child_reports_its_outcome():
    mutation = ScriptedMutation()

    result = solve(
        PROBLEM,
        random.Random(0),
        max_generations=3,
        mutation=mutation,
        clock=fake_clock(),
        population_size=5,
    )

    # Default rate 1.0: every iteration mutates and reports once.
    assert mutation.calls == len(mutation.outcomes) == 5 * result.generations


def test_population_size_must_be_at_least_one():
    with pytest.raises(ValueError, match="population_size"):
        solve(PROBLEM, random.Random(0), population_size=0)


# UniformMutation


@pytest.mark.parametrize("seed", range(10))
def test_uniform_mutation_stays_feasible_and_places_everyone_when_there_is_room(seed):
    problem = random_problem(seed)
    rng = random.Random(seed)
    individual = split(problem, rng.sample(range(12), 12))

    mutated = UniformMutation(problem)(individual, rng)

    assert mutated.unassigned == []
    assert_feasible(problem, mutated)
