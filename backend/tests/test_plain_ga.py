"""The plain-GA baseline (#203): its mutation, run plan and statistics."""

import random

import pytest

from app.solver.ga import solve
from app.solver.individual import split
from app.solver.instances import morning_wave
from app.solver.mutation import ClassicMutation, relocate_position, swap_positions
from benchmarks import plain_ga as pg
from tests.solver_checks import assert_feasible

PROBLEM = morning_wave(n_crew=12, n_vans=4, seed=1)


def test_swap_exchanges_two_positions_and_leaves_the_input():
    tour = [10, 11, 12, 13]

    assert swap_positions(tour, 0, 2) == [12, 11, 10, 13]
    assert tour == [10, 11, 12, 13]


def test_relocate_moves_one_pickup_and_leaves_the_input():
    tour = [10, 11, 12, 13]

    assert relocate_position(tour, 0, 2) == [11, 12, 10, 13]
    assert relocate_position(tour, 3, 0) == [13, 10, 11, 12]
    assert tour == [10, 11, 12, 13]


def test_classic_mutation_keeps_every_pickup_exactly_once():
    individual = split(PROBLEM, list(range(12)))
    before = individual.copy()
    mutation = ClassicMutation(PROBLEM)
    rng = random.Random(3)

    for _ in range(100):
        mutated = mutation(individual, rng)
        assert_feasible(PROBLEM, mutated)

    assert individual == before


def test_classic_mutation_varies_the_tour():
    # Both moves use two distinct positions, so over
    # many draws the mutation reaches more than one tour.
    individual = split(PROBLEM, list(range(12)))
    mutation = ClassicMutation(PROBLEM)
    rng = random.Random(1)

    tours = {tuple(mutation(individual, rng).giant_tour()) for _ in range(50)}

    assert len(tours) > 1


def test_a_solve_with_classic_mutation_is_feasible():
    result = solve(
        PROBLEM,
        random.Random(1),
        max_generations=3,
        mutation=ClassicMutation(PROBLEM),
        clock=lambda: 0.0,
    )

    assert_feasible(PROBLEM, result.best)


def test_the_plan_is_the_agreed_design():
    runs = pg.plan(seeds=10)

    # 20 Solomon x 2 methods, wave x 3, smoke x 2.
    assert len(runs) == 20 * 10 * 2 + 10 * 3 + 10 * 2
    assert sum(r.time_limit_sec for r in runs) == 20 * 10 * 2 * 60 + 10 * 3 * 120 + 10 * 2 * 30
    methods = {(r.instance, r.method) for r in runs}
    assert ("R101", "plain_ga") in methods and ("RC108", "ga_alns") in methods
    assert ("R101", "uniform") not in methods
    assert ("morning_wave_120", "uniform") in methods
    assert ("smoke_30", "plain_ga") not in methods


def test_the_method_order_alternates_by_seed():
    runs = [r for r in pg.plan(seeds=2) if r.instance == "R101"]

    assert [(r.seed, r.method) for r in runs] == [
        (1, "ga_alns"), (1, "plain_ga"), (2, "plain_ga"), (2, "ga_alns"),
    ]  # fmt: skip


def test_only_the_time_limit_stops_a_run(monkeypatch):
    seen = {}

    def fake_solve(problem, rng, **kwargs):
        seen.update(kwargs)
        raise StopIteration

    monkeypatch.setattr(pg, "solve", fake_solve)
    with pytest.raises(StopIteration):
        pg.run_one(pg.Run("smoke_30", "uniform", 1, 30.0))

    assert seen["time_limit_sec"] == 30.0
    assert seen["max_generations"] == seen["no_improvement_generations"] == pg.NO_LIMIT


def test_a_real_run_gives_a_complete_row():
    row = pg.run_one(pg.Run("smoke_30", "plain_ga", 1, 0.2))

    assert set(row) == set(pg.COLUMNS)
    assert row["every_pickup_once"] is True
    assert row["generations"] >= 1 and row["distance"] > 0


def test_a_resumed_run_skips_what_is_done(tmp_path):
    def fake(run):
        return dict.fromkeys(pg.COLUMNS, 1) | {
            "instance": run.instance, "method": run.method, "seed": run.seed,
        }  # fmt: skip

    runs = [pg.Run("A", "plain_ga", 1, 1.0), pg.Run("A", "ga_alns", 1, 1.0)]
    pg.run_all(runs[:1], tmp_path, resume=False, solve_run=fake)

    called = []
    rows = pg.run_all(
        runs, tmp_path, resume=True, solve_run=lambda run: called.append(run) or fake(run)
    )

    assert called == [runs[1]]
    assert len(rows) == 2


def test_wilcoxon_by_hand():
    # Ten positive differences, no ties: the smallest two-sided exact p, 2 / 2^10.
    assert pg.wilcoxon_p([float(k) for k in range(1, 11)]) == pytest.approx(2 / 1024)


def test_wilcoxon_with_no_difference_is_1():
    assert pg.wilcoxon_p([0.0] * 10) == 1.0


def test_wilcoxon_drops_zero_differences():
    with_zeros = [0.0, 0.0, *[float(k) for k in range(1, 9)]]

    assert pg.wilcoxon_p(with_zeros) == pytest.approx(pg.wilcoxon_p(with_zeros[2:]))


def test_holm_by_hand():
    # Sorted 0.01, 0.03, 0.04 x 3, 2, 1 = 0.03, 0.06, 0.04, kept non-decreasing.
    assert pg.holm([0.01, 0.04, 0.03]) == pytest.approx([0.03, 0.06, 0.06])


def test_holm_is_capped_at_1():
    assert pg.holm([0.6, 0.7]) == pytest.approx([1.0, 1.0])


def test_a_tiny_p_is_not_shown_as_zero():
    assert pg._star(9.5e-7) == "<0.0001 *"
    assert pg._star(0.0410) == "0.0410 *"
    assert pg._star(0.55) == "0.5500"


def test_a_rebuild_keeps_the_hand_written_notes():
    old = "old tables\n\n## Notes\n\nGA-ALNS wins.\n"

    assert pg.with_notes("new tables", old) == "new tables\n\n## Notes\n\nGA-ALNS wins."
    assert pg.with_notes("new tables", "old tables only") == "new tables"


def test_the_summary_shows_unassigned_pickups():
    rows = [
        {"instance": "A", "method": m, "seed": s, "cost": c, "vehicles": 1, "distance": 1.0,
         "late_crew": 0, "unassigned": u, "generations": 1,
         "every_pickup_once": "True", "checker_feasible": "True"}
        for m, s, c, u in [("plain_ga", 1, 9.0, 3), ("ga_alns", 1, 1.0, 0)]
    ]  # fmt: skip

    means = next(line for line in pg.summary(rows).splitlines() if line.startswith("| A | 9"))

    assert "Unassigned plain_ga" in pg.summary(rows)
    assert "| 3.0 | 0.0 |" in means


def test_paired_differences_are_per_seed_and_only_for_common_seeds():
    rows = [
        {"instance": "A", "method": "plain_ga", "seed": 1, "cost": 10.0},
        {"instance": "A", "method": "ga_alns", "seed": 1, "cost": 7.0},
        {"instance": "A", "method": "plain_ga", "seed": 2, "cost": 5.0},
    ]

    assert pg.paired(rows, "A", "cost", "plain_ga", "ga_alns") == [3.0]
