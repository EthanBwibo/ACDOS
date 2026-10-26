"""Shaw removal (Shaw, 1998; Ropke and Pisinger, 2006), an ALNS destroy operator.

Takes out pickups that are related to each other (close together, reporting
at similar times), so re-insertion can regroup them: removing unrelated
pickups tends to put each one straight back where it was.

Adapted to many-to-one from Ropke and Pisinger (R&P):
- The time term compares report times (deadlines at JKIA), not scheduled
  pickup times. The report time decides whether two crew can share a van, and
  it is fixed input, so the matrix is built once per Problem.
- R&P's vehicle-compatibility term is dropped: any vehicle can take any crew
  member.
- On Solomon's instances (#99) the time term compares due times at the stop
  (problem.urgency), where R&P compare the times service starts in the
  current solution. A fixed time keeps the matrix built once per Problem.
"""

import math
import random

from app.solver.individual import Individual
from app.solver.problem import Problem, urgency
from app.solver.removal import take_out

# R&P's relatedness weights (phi, chi, psi). Sensitivity run against 9/9/2 is
# planned (#14): crew in one zone reporting hours apart cannot share a van.
SHAW_DISTANCE_WEIGHT = 9.0
SHAW_TIME_WEIGHT = 3.0
SHAW_DEMAND_WEIGHT = 2.0
# R&P's p: higher picks the most related pickup more often.
SHAW_DETERMINISM = 6


def relatedness_matrix(problem: Problem) -> list[list[float]]:
    """R[i][j] for every pair of pickups; lower means more related.

    R = phi * distance + chi * report-time gap + psi * demand gap, each term
    divided by its largest value so it lies in [0, 1].

    Distance is straight-line (Problem.distance, haversine for crew): there
    are no road times between pickups, only from each zone to JKIA. The time
    is urgency(): the report time for crew, the due time on Solomon's
    instances.
    """
    pickups = problem.pickups
    distance = [[problem.distance(a.location, b.location) for b in pickups] for a in pickups]
    report_gap = [[_report_gap(urgency(a), urgency(b)) for b in pickups] for a in pickups]
    demand_gap = [[abs(a.demand - b.demand) for b in pickups] for a in pickups]

    distance, report_gap, demand_gap = (_normalise(m) for m in (distance, report_gap, demand_gap))
    n = len(pickups)
    return [
        [
            SHAW_DISTANCE_WEIGHT * distance[i][j]
            + SHAW_TIME_WEIGHT * report_gap[i][j]
            + SHAW_DEMAND_WEIGHT * demand_gap[i][j]
            for j in range(n)
        ]
        for i in range(n)
    ]


def _report_gap(a: float, b: float) -> float:
    # Pickups with no report time (infinite deadline, only in tests) are alike
    # to each other and as unlike as possible to the rest.
    if math.isinf(a) and math.isinf(b):
        return 0.0
    if math.isinf(a) or math.isinf(b):
        return math.inf
    return abs(a - b)


def _normalise(matrix: list[list[float]]) -> list[list[float]]:
    """Divide by the largest finite value; infinite becomes 1, all-zero stays 0."""
    largest = max((v for row in matrix for v in row if math.isfinite(v)), default=0.0)
    return [
        [1.0 if math.isinf(v) else (v / largest if largest > 0 else 0.0) for v in row]
        for row in matrix
    ]


def shaw_removal(
    individual: Individual,
    relatedness: list[list[float]],
    q: int,
    rng: random.Random,
    determinism: float = SHAW_DETERMINISM,
) -> tuple[Individual, list[int]]:
    """Remove q related pickups from the routes.

    Returns a new Individual with the removed pickups appended to unassigned
    (so every pickup is still placed exactly once), and the removed pickups in
    the order they were taken. The input is not changed.

    The first pickup is chosen at random. Each next one: pick a pickup already
    removed, sort the rest by relatedness to it, and take the one at index
    floor(y^p * count) for y uniform in [0, 1). y^p is usually small, so the
    most related pickups are the likeliest, but not certain, to go.
    """
    remaining = [i for route in individual.routes for i in route]
    q = min(q, len(remaining))
    if q <= 0:
        return individual.copy(), []

    removed = [remaining.pop(rng.randrange(len(remaining)))]
    while len(removed) < q:
        r = rng.choice(removed)
        # Index as tie-break so the order never depends on earlier sorts.
        remaining.sort(key=lambda j: (relatedness[r][j], j))
        removed.append(remaining.pop(int(rng.random() ** determinism * len(remaining))))

    return take_out(individual, removed), removed
