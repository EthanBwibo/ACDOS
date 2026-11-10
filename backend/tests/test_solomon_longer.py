"""The 300 s Solomon runs against #203's 60 s ones (#211)."""

from benchmarks import plain_ga as pg
from benchmarks import solomon_longer as sl


def test_the_plan_is_four_instances_ten_seeds_300_s_ga_alns():
    runs = sl.plan(seeds=10)

    assert len(runs) == 40
    assert {r.instance for r in runs} == {"R101", "R105", "RC101", "RC105"}
    assert {(r.method, r.time_limit_sec) for r in runs} == {("ga_alns", 300.0)}
    assert sorted({r.seed for r in runs}) == list(range(1, 11))


def test_the_60_s_runs_are_203s_ga_alns_runs_on_these_instances():
    short = sl.short_runs()

    assert len(short) == 40
    assert {r["method"] for r in short} == {"ga_alns"}
    assert {r["time_limit_sec"] for r in short} == {"60.0"}


def test_gap_closed_by_hand():
    assert sl.gap_closed(4.0, 1.0) == "75%"
    assert sl.gap_closed(2.0, 2.0) == "0%"
    assert sl.gap_closed(0.0, 0.0) == "-"  # nothing to close


def test_a_run_is_feasible_only_with_the_check_passed_and_nobody_unassigned():
    assert sl.feasible({"checker_feasible": "True", "unassigned": "0"})
    assert not sl.feasible({"checker_feasible": "False", "unassigned": "0"})
    assert not sl.feasible({"checker_feasible": "True", "unassigned": "2"})


def row(name, seed, vehicles, distance):
    return {"instance": name, "seed": seed, "vehicles": vehicles, "distance": distance,
            "generations": 40, "checker_feasible": "True", "unassigned": 0}  # fmt: skip


def test_the_change_table_pairs_by_seed():
    short = [row(n, s, 20, 1800.0) for n in sl.INSTANCES for s in range(1, 11)]
    long = [row(n, s, 19, 1700.0) for n in sl.INSTANCES for s in range(1, 11)]

    lines = sl.change_table(short, long)

    r101 = next(line for line in lines if line.startswith("| R101"))
    # One van and 100 fewer on every seed: 10 better, exact p 2/1024, x4 by Holm.
    assert r101.startswith("| R101 | -1.00 | 10/0/0 | ")
    assert "| -100.00 | 10/0/0 |" in r101
    assert r101.count(pg._star(4 * 2 / 1024)) == 2


def test_the_summary_builds_from_real_60_s_runs():
    short = sl.short_runs()
    long = [dict(r, time_limit_sec="300.0") for r in short]

    text = sl.summary(short, long)

    assert "| R101 | 19 / 1650.80 |" in text
    # The same runs on both sides: nothing changes, and every test gives p = 1.
    assert text.count("1.0000") == 8
