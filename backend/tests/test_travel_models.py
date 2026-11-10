"""On-time rates for the travel-model comparison (#210)."""

import random

from app.solver.ga import solve
from app.solver.individual import schedule
from app.solver.instances import morning_wave
from benchmarks import travel_models as tm


def run(seed, on_time, travel="rf"):
    return {"travel": travel, "seed": seed, "on_time": on_time}


def cross(seed, fixed, retimed, crew=120):
    return {"seed": seed, "crew": crew, "on_time_fixed": fixed, "on_time_retimed": retimed}


def test_on_time_rates_are_shares_of_all_crew():
    rates = tm.on_time_by_seed([run(1, 114), run(1, 120, "haversine")], [cross(1, 60, 108)])

    assert rates == {1: {"rf": 95.0, "fixed": 50.0, "retimed": 90.0}}


def test_the_table_reports_means_ranges_and_paired_tests():
    runs = [run(s, 120) for s in range(1, 11)]
    crosses = [cross(s, 60 + s, 120 - (s % 2)) for s in range(1, 11)]

    lines = tm.on_time_table(runs, crosses)

    mean_row = next(line for line in lines if line.startswith("| Mean"))
    # Fixed: 61 to 70 of 120, mean 65.5 -> 54.6%. Re-timed: 119 or 120.
    assert "54.6 (50.8 to 58.3)" in mean_row
    fixed_test = next(line for line in lines if line.startswith("| Haversine plan, fixed"))
    # Better on all 10 seeds: exact p 2/1024, times 2 by Holm.
    assert "10/0/0" in fixed_test and f"{2 * 2 / 1024:.4f} *" in fixed_test
    retimed_test = next(line for line in lines if line.startswith("| Haversine plan, re-timed"))
    assert "5/5/0" in retimed_test


def test_a_plan_under_the_travel_it_was_made_with_loses_no_one():
    # Cross-evaluated against itself, nobody on time becomes late, so the
    # fixed and re-timed counts are the plan's own on-time count.
    problem = morning_wave(n_crew=12, n_vans=4, seed=1)
    result = solve(problem, random.Random(1), max_generations=3, clock=lambda: 0.0)
    on_time = sum(s.lateness == 0 for r in schedule(problem, result.best) for s in r.stops)

    c = tm.cross_evaluation(problem, problem, result.best)

    assert c["on_time_fixed"] == c["on_time_retimed"] == on_time
    assert c["late_fixed"] == c["late_retimed"] == 0
