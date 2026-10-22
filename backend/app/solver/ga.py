"""The steady-state GA loop that ties the solver together (#74).

One iteration:
1. Binary tournament, twice: the cheaper of two random individuals is a
   parent; the second tournament leaves out the first parent.
2. Order crossover (#9) gives one child.
3. Mutation, with probability MUTATION_RATE: one ALNS destroy and one repair.
   In GA-ALNS the destroy-and-repair step takes the place of mutation.
4. Steady-state replacement: the child replaces the worst individual if it is
   cheaper than the worst and not already in the population.
5. The outcome is reported to the mutation, for the adaptive operator scores
   (#71): "accepted" in Ropke and Pisinger's sense means step 4 succeeded.
   The mutation is adaptive (mutation.AdaptiveMutation) unless the caller
   passes another, such as the uniform baseline.

Elitism: only the worst individual is ever replaced, and only by a cheaper
one, so the best individual always survives and the best cost never rises.

A generation is POPULATION_SIZE iterations, so generation counts compare with
a generational GA. The run stops at MAX_GENERATIONS, after TIME_LIMIT_SEC, or
after NO_IMPROVEMENT_GENERATIONS generations without a new best, whichever
comes first. All of these are tuned in #14.
"""

import enum
import random
import time
from collections.abc import Callable
from dataclasses import dataclass

from app.solver.crossover import order_crossover
from app.solver.fitness import Evaluation, evaluate, fitness
from app.solver.individual import Individual
from app.solver.mutation import AdaptiveMutation, Mutation, Outcome
from app.solver.nearest_neighbour import nearest_neighbour
from app.solver.population import StructureKey, initial_population, structure_key
from app.solver.problem import Problem

POPULATION_SIZE = 30
MAX_GENERATIONS = 200
TIME_LIMIT_SEC = 30.0
NO_IMPROVEMENT_GENERATIONS = 30
# Probability that a child gets the destroy-and-repair step. 1.0: every child.
MUTATION_RATE = 1.0


class StopReason(enum.Enum):
    MAX_GENERATIONS = "max_generations"
    TIME_LIMIT = "time_limit"
    NO_IMPROVEMENT = "no_improvement"


class Population:
    """The individuals with their costs and structure keys, plus every key
    ever seen (for "never seen before" in the scores)."""

    def __init__(self, problem: Problem, individuals: list[Individual]) -> None:
        self.problem = problem
        self.individuals = list(individuals)
        self.costs = [fitness(problem, individual) for individual in self.individuals]
        self.keys = [structure_key(problem, individual) for individual in self.individuals]
        self.seen: set[StructureKey] = set(self.keys)

    @property
    def best_cost(self) -> float:
        # Read from the costs, not kept as a running minimum, so the history
        # would show it if the best individual were ever lost.
        return min(self.costs)

    def tournament(self, rng: random.Random, exclude: int | None = None) -> int:
        """Index of the cheaper of two individuals drawn at random, leaving out
        exclude when there is anyone else. Lower index on a tie."""
        candidates = [i for i in range(len(self.individuals)) if i != exclude] or [exclude]
        drawn = rng.sample(candidates, min(2, len(candidates)))
        return min(drawn, key=lambda i: (self.costs[i], i))

    def offer(self, child: Individual, cost: float, cost_before_mutation: float) -> Outcome:
        """Replace the worst individual with child if it is cheaper and new."""
        key = structure_key(self.problem, child)
        worst = max(range(len(self.costs)), key=lambda i: (self.costs[i], i))
        accepted = cost < self.costs[worst] and key not in self.keys
        never_seen = key not in self.seen
        self.seen.add(key)
        if not accepted:
            return Outcome.NO_SCORE

        new_best = cost < self.best_cost
        self.individuals[worst], self.costs[worst], self.keys[worst] = child, cost, key
        if new_best:
            return Outcome.NEW_BEST
        if cost < cost_before_mutation:
            return Outcome.IMPROVED
        return Outcome.ACCEPTED_NEW if never_seen else Outcome.NO_SCORE

    def best(self) -> Individual:
        return self.individuals[min(range(len(self.costs)), key=lambda i: (self.costs[i], i))]


@dataclass(frozen=True)
class GenerationStats:
    generation: int
    best_cost: float
    mean_cost: float
    elapsed_sec: float


@dataclass(frozen=True)
class SolveResult:
    best: Individual
    evaluation: Evaluation
    stop_reason: StopReason
    generations: int
    history: tuple[GenerationStats, ...]
    population: tuple[Individual, ...]


def solve(
    problem: Problem,
    rng: random.Random,
    *,
    population_size: int = POPULATION_SIZE,
    max_generations: int = MAX_GENERATIONS,
    time_limit_sec: float = TIME_LIMIT_SEC,
    no_improvement_generations: int = NO_IMPROVEMENT_GENERATIONS,
    mutation_rate: float = MUTATION_RATE,
    mutation: Mutation | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> SolveResult:
    """Run the GA from a population seeded with the nearest-neighbour solution.

    The same rng seed gives the same run, as long as the time limit is not
    what stops it (pass a fake clock to make even that repeatable).
    """
    if population_size < 1:
        raise ValueError("population_size must be at least 1")
    started = clock()
    mutation = mutation or AdaptiveMutation(problem)
    population = Population(
        problem,
        initial_population(problem, population_size, rng, seeds=(nearest_neighbour(problem),)),
    )
    history: list[GenerationStats] = []
    generations = since_improvement = 0
    stop_reason = None

    while stop_reason is None:
        best_before = population.best_cost
        for _ in range(population_size):
            if clock() - started >= time_limit_sec:
                stop_reason = StopReason.TIME_LIMIT
                break
            _iterate(problem, population, mutation, mutation_rate, rng)
        generations += 1
        since_improvement = 0 if population.best_cost < best_before else since_improvement + 1
        history.append(
            GenerationStats(
                generation=generations,
                best_cost=population.best_cost,
                mean_cost=sum(population.costs) / len(population.costs),
                elapsed_sec=clock() - started,
            )
        )
        if stop_reason is None and generations >= max_generations:
            stop_reason = StopReason.MAX_GENERATIONS
        elif stop_reason is None and since_improvement >= no_improvement_generations:
            stop_reason = StopReason.NO_IMPROVEMENT

    best = population.best()
    return SolveResult(
        best=best,
        evaluation=evaluate(problem, best),
        stop_reason=stop_reason,
        generations=generations,
        history=tuple(history),
        population=tuple(population.individuals),
    )


def _iterate(
    problem: Problem,
    population: Population,
    mutation: Mutation,
    mutation_rate: float,
    rng: random.Random,
) -> None:
    first = population.tournament(rng)
    second = population.tournament(rng, exclude=first)
    child = order_crossover(
        problem, population.individuals[first], population.individuals[second], rng
    )
    cost_before = fitness(problem, child)
    if rng.random() >= mutation_rate:
        # Not mutated: no operator ran, so nothing is scored.
        population.offer(child, cost_before, cost_before)
        return
    mutated = mutation(child, rng)
    mutation.record(population.offer(mutated, fitness(problem, mutated), cost_before))
