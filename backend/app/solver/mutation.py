"""The GA's mutation step: one ALNS destroy and one repair (#74, #71).

Two ways of choosing the operators:
- UniformMutation: every destroy operator equally likely. The non-adaptive
  baseline for the results chapter.
- AdaptiveMutation: Ropke and Pisinger's (2006) adaptive selection. Each
  operator has a weight; destroy and repair are each chosen by roulette in
  proportion to the weights; operators earn scores for the outcomes they
  produce, and every SEGMENT_LENGTH mutations the weights move towards each
  operator's average score.

Adapted to the GA: R&P score a new solution by whether simulated annealing
accepts it. Here "accepted" means the child entered the population (it
replaced the worst individual, #74), so:
  sigma 1 (33): accepted and a new best in the population
  sigma 2 (9):  accepted and cheaper than the child before mutation
  sigma 3 (13): accepted, not cheaper, and never seen before
  0:            rejected, or accepted but seen before
"""

import csv
import enum
import functools
import random
from collections.abc import Callable
from dataclasses import astuple, dataclass, fields
from pathlib import Path
from typing import Protocol

from app.solver.individual import Individual
from app.solver.insertion import greedy_insertion
from app.solver.problem import Problem
from app.solver.removal import random_removal, removal_count, unavoidable_costs, worst_removal
from app.solver.shaw import relatedness_matrix, shaw_removal

# R&P's scores and reaction factor.
SIGMA_NEW_BEST = 33.0
SIGMA_IMPROVED = 9.0
SIGMA_ACCEPTED_NEW = 13.0
REACTION_FACTOR = 0.1
# Mutations per weight update. R&P use 100 over about 25,000 iterations; a
# 120 s run on 120 crew manages only a few hundred iterations (#71), so 50,
# to get more than a handful of updates. 25/50/100 are compared in #14.
SEGMENT_LENGTH = 50


class Outcome(enum.Enum):
    """What happened to a mutated child, in Ropke and Pisinger's score terms."""

    NEW_BEST = "new_best"  # sigma 1: cheapest in the population so far
    IMPROVED = "improved"  # sigma 2: accepted, cheaper than before mutation
    ACCEPTED_NEW = "accepted_new"  # sigma 3: accepted, not cheaper, never seen before
    NO_SCORE = "no_score"  # rejected, or accepted but seen before


SCORES = {
    Outcome.NEW_BEST: SIGMA_NEW_BEST,
    Outcome.IMPROVED: SIGMA_IMPROVED,
    Outcome.ACCEPTED_NEW: SIGMA_ACCEPTED_NEW,
    Outcome.NO_SCORE: 0.0,
}

Destroy = Callable[[Individual, int, random.Random], tuple[Individual, list[int]]]
Repair = Callable[[Individual], Individual]


class Mutation(Protocol):
    """The destroy-and-repair step the GA loop calls."""

    def __call__(self, individual: Individual, rng: random.Random) -> Individual: ...

    def record(self, outcome: Outcome) -> None: ...


def destroy_operators(problem: Problem) -> dict[str, Destroy]:
    """Every destroy operator, called as op(individual, q, rng), with its data
    (relatedness matrix, floor) built once per problem."""
    relatedness = relatedness_matrix(problem)
    floor = unavoidable_costs(problem)
    return {
        # A lambda for Shaw: its matrix comes before q, so partial cannot bind it (#78).
        "shaw": lambda individual, q, rng: shaw_removal(individual, relatedness, q, rng),
        "random": random_removal,
        "worst": functools.partial(worst_removal, problem, floor=floor),
    }


def repair_operators(problem: Problem) -> dict[str, Repair]:
    """Every repair operator, called as op(individual). Regret-2 joins when
    #70 is built."""
    return {"greedy": functools.partial(greedy_insertion, problem)}


def _destroy_and_repair(
    destroy: Destroy, repair: Repair, individual: Individual, rng: random.Random
) -> Individual:
    routed = sum(len(route) for route in individual.routes)
    destroyed, _ = destroy(individual, removal_count(routed, rng), rng)
    return repair(destroyed)


class UniformMutation:
    """Shaw, random or worst removal with equal probability, then greedy
    insertion. The non-adaptive baseline."""

    def __init__(self, problem: Problem) -> None:
        self.destroy = list(destroy_operators(problem).values())
        self.repair = repair_operators(problem)["greedy"]

    def __call__(self, individual: Individual, rng: random.Random) -> Individual:
        return _destroy_and_repair(rng.choice(self.destroy), self.repair, individual, rng)

    def record(self, outcome: Outcome) -> None:
        pass  # nothing adapts


@dataclass(frozen=True)
class SegmentRow:
    """One operator at the end of one segment, for the weight charts."""

    segment: int
    kind: str  # "destroy" or "repair"
    operator: str
    uses: int
    score: float
    weight: float  # after this segment's update


class AdaptiveMutation:
    """Ropke and Pisinger's adaptive operator selection (see module docstring).

    Each segment, an operator's weight becomes
        w * (1 - r) + r * score / uses
    An operator not used in the segment keeps its weight (no division by zero).
    One that is used but never scores decays by (1 - r) each segment and never
    reaches 0, so it can always be picked again. Only whole segments update
    the weights and are logged.
    """

    def __init__(
        self,
        problem: Problem,
        segment_length: int = SEGMENT_LENGTH,
        reaction_factor: float = REACTION_FACTOR,
    ) -> None:
        self.operators: dict[str, dict[str, Callable]] = {
            "destroy": destroy_operators(problem),
            "repair": repair_operators(problem),
        }
        self.segment_length = segment_length
        self.reaction_factor = reaction_factor
        self.weights = {kind: dict.fromkeys(ops, 1.0) for kind, ops in self.operators.items()}
        self.log: list[SegmentRow] = []
        self._segment = 0
        self._recorded = 0
        self._last: dict[str, str] = {}
        self._reset_segment()

    def __call__(self, individual: Individual, rng: random.Random) -> Individual:
        self._last = {kind: self._roulette(kind, rng) for kind in ("destroy", "repair")}
        destroy = self.operators["destroy"][self._last["destroy"]]
        repair = self.operators["repair"][self._last["repair"]]
        return _destroy_and_repair(destroy, repair, individual, rng)

    def record(self, outcome: Outcome) -> None:
        """Credit both operators just used with the outcome's score."""
        for kind, name in self._last.items():
            self._uses[kind][name] += 1
            self._scores[kind][name] += SCORES[outcome]
        self._recorded += 1
        if self._recorded == self.segment_length:
            self._end_segment()

    def _roulette(self, kind: str, rng: random.Random) -> str:
        names = list(self.weights[kind])
        return rng.choices(names, weights=[self.weights[kind][n] for n in names])[0]

    def _end_segment(self) -> None:
        self._segment += 1
        r = self.reaction_factor
        for kind, weights in self.weights.items():
            for name, weight in weights.items():
                uses, score = self._uses[kind][name], self._scores[kind][name]
                if uses:
                    weights[name] = weight * (1 - r) + r * score / uses
                self.log.append(SegmentRow(self._segment, kind, name, uses, score, weights[name]))
        self._reset_segment()

    def _reset_segment(self) -> None:
        self._recorded = 0
        self._uses = {kind: dict.fromkeys(ops, 0) for kind, ops in self.operators.items()}
        self._scores = {kind: dict.fromkeys(ops, 0.0) for kind, ops in self.operators.items()}


def write_operator_log(rows: list[SegmentRow], path: Path) -> None:
    """The weights per segment as CSV, one row per operator per segment."""
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow([f.name for f in fields(SegmentRow)])
        writer.writerows(astuple(row) for row in rows)
