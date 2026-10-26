"""Solomon benchmark loader, independent checker and harness (#13)."""

import random

import pytest

from app.solver.fitness import evaluate
from app.solver.ga import solve
from app.solver.individual import Individual
from app.solver.weights import SOLOMON
from benchmarks import solomon
from benchmarks.solomon_harness import comparison_label, expand, run_one, summary
from tests.solver_checks import assert_feasible

# A three-customer instance in Solomon's format, small enough to check by hand.
# Depot at (0, 0), open 0 to 100. Customer 1 at (0, 10), customer 2 at
# (0, 20), customer 3 at (10, 0).
TINY = """TINY

VEHICLE
NUMBER     CAPACITY
  2          10

CUSTOMER
CUST NO.  XCOORD.   YCOORD.    DEMAND   READY TIME  DUE DATE   SERVICE   TIME

    0       0          0          0          0        100          0
    1       0         10          4          0         50          5
    2       0         20          4         30         40          5
    3      10          0          6          0         20          0
"""


@pytest.fixture
def tiny(tmp_path):
    path = tmp_path / "tiny.txt"
    path.write_text(TINY, encoding="ascii")
    return solomon.load(path)


def test_load_reads_the_fleet_depot_and_customers(tiny):
    assert (tiny.name, tiny.vehicles, tiny.capacity) == ("TINY", 2, 10)
    assert tiny.depot == solomon.Customer(0, 0, 0, 0, 0, 100, 0)
    assert tiny.customers[1] == solomon.Customer(2, 0, 20, 4, 30, 40, 5)
    assert len(tiny.customers) == 3
    assert not tiny.truncated


def test_load_finds_an_instance_by_name():
    r101 = solomon.load("R101")

    assert (r101.name, r101.vehicles, r101.capacity) == ("R101", 25, 200)
    assert len(r101.customers) == 100
    assert r101.depot == solomon.Customer(0, 35, 35, 0, 0, 230, 0)
    assert r101.customers[0] == solomon.Customer(1, 41, 49, 10, 161, 171, 10)
    assert r101.customers[-1] == solomon.Customer(100, 18, 18, 17, 185, 195, 10)


def test_customers_keeps_the_first_n():
    r101 = solomon.load("R101", customers=25)

    assert [c.number for c in r101.customers] == list(range(1, 26))
    assert r101.truncated
    assert r101.full_size == 100
    with pytest.raises(ValueError):
        solomon.load("R101", customers=101)


def test_check_routes_accepts_a_feasible_plan_and_measures_it(tiny):
    # [1, 2]: 10 to customer 1 (start 10, due 50), served to 15, 10 more to
    # customer 2 at 25, waits to 30 (due 40), served to 35, 20 back: 55.
    # [3]: 10 there (due 20), 10 back. Load 8 and 6. Distance 40 + 20 = 60.
    check = solomon.check_routes(tiny, [[1, 2], [3]])

    assert check.feasible, check.violations
    assert (check.vehicles, check.distance) == (2, 60)


@pytest.mark.parametrize(
    ("routes", "broken"),
    [
        ([[1, 2]], "not visited [3]"),
        ([[1, 2], [3, 1]], "more than once [1]"),
        ([[1, 2, 3]], "carries 14 > 10"),
        # 2 first: reached at 20, waits to 30 (due 40), served to 35; customer
        # 1 at 45 (due 50), served to 50, back at 60. Feasible.
        ([[2, 1], [3]], None),
        ([[1], [2], [3]], "fleet has 2"),
        ([[3, 1], [2]], None),
        ([[1, 3], [2]], "customer 3 starts at"),
    ],
)
def test_check_routes_reports_each_broken_rule(tiny, routes, broken):
    check = solomon.check_routes(tiny, routes)

    if broken is None:
        assert check.feasible, check.violations
    else:
        assert not check.feasible
        assert any(broken in v for v in check.violations), check.violations


def test_check_routes_reports_a_late_return_to_the_depot(tmp_path):
    late_depot = TINY.replace("0        100          0", "0         50          0")
    path = tmp_path / "late.txt"
    path.write_text(late_depot, encoding="ascii")

    # [1, 2] is back at 55, after the depot closes at 50.
    check = solomon.check_routes(solomon.load(path), [[1, 2], [3]])

    assert any("back at the depot" in v for v in check.violations), check.violations


@pytest.mark.parametrize("name", solomon.instance_names())
def test_the_published_best_known_solution_checks_out(name):
    # SINTEF's solution files must be feasible and give exactly the vehicles
    # and the distance (2 decimals) in best_known.csv: this checks the loader,
    # the checker, full precision, and the table, all at once.
    instance = solomon.load(name)
    best = solomon.best_known()[name]

    check = solomon.check_routes(
        instance, solomon.read_solution(solomon.SOLUTIONS_DIR / f"{name.lower()}.txt")
    )

    assert check.feasible, check.violations
    assert check.vehicles == best.vehicles
    assert round(check.distance, 2) == best.distance


@pytest.mark.parametrize("name", solomon.instance_names())
def test_the_solver_costs_the_best_known_solution_as_on_time(name):
    # The same solutions through to_problem and the solver's own fitness: no
    # lateness, the same vehicles, and D equal to the checker's distance. So
    # every best-known solution is one the solver can represent.
    instance = solomon.load(name)
    problem = solomon.to_problem(instance)
    index = {int(p.id): i for i, p in enumerate(problem.pickups)}
    routes = [
        [index[n] for n in route]
        for route in solomon.read_solution(solomon.SOLUTIONS_DIR / f"{name.lower()}.txt")
    ]
    routes += [[] for _ in range(len(problem.vehicles) - len(routes))]

    evaluation = evaluate(problem, Individual(routes))
    check = solomon.check_routes(instance, solomon.routes_as_customers(problem, routes))

    assert evaluation.lateness_sec == 0
    assert evaluation.vehicles_used == check.vehicles
    assert evaluation.distance == pytest.approx(check.distance, abs=1e-9)


def test_to_problem_keeps_the_windows_and_the_fleet(tiny):
    problem = solomon.to_problem(tiny)

    assert problem.weights is SOLOMON
    assert problem.stop_windows
    second = problem.pickups[1]
    assert (second.id, second.ready, second.due, second.demand) == ("2", 30, 40, 4)
    assert second.service_sec == 5
    assert second.deadline == 100  # back at the depot before it closes
    assert len(problem.vehicles) == 2
    assert all(v.capacity == 10 and v.available_from == 0 for v in problem.vehicles)
    assert problem.destination == problem.vehicles[0].start


def test_a_solve_on_25_customers_passes_both_checks():
    instance = solomon.load("C101", customers=25)
    problem = solomon.to_problem(instance)

    result = solve(problem, random.Random(1), max_generations=3, clock=lambda: 0.0)

    assert_feasible(problem, result.best)
    check = solomon.check_routes(instance, solomon.routes_as_customers(problem, result.best.routes))
    on_time = result.evaluation.lateness_sec == 0 and result.evaluation.unassigned == 0
    assert check.feasible == on_time
    assert check.vehicles == result.evaluation.vehicles_used
    assert check.distance == pytest.approx(result.evaluation.distance, abs=1e-9)


def test_a_truncated_run_is_never_compared_with_the_100_customer_best_known():
    row = run_one("C101", seed=1, time_limit_sec=2.0, customers=25)

    assert row["customers"] == 25
    assert row["comparison"] == "no comparison"
    assert row["best_known_vehicles"] == row["vehicle_gap"] == ""


def test_comparison_label():
    assert comparison_label(True, True, True) == "no comparison"
    assert comparison_label(False, True, True) == "compared"
    assert comparison_label(False, True, False) == "infeasible"
    assert comparison_label(False, False, True) == "infeasible"


def test_expand_turns_groups_into_instances():
    assert expand(["R1"]) == [f"R1{k:02d}" for k in range(1, 13)]
    assert expand(["rc1", "c101"]) == [f"RC1{k:02d}" for k in range(1, 9)] + ["C101"]
    with pytest.raises(ValueError):
        expand(["C2"])


def test_summary_keeps_truncated_runs_apart():
    def row(customers, vehicles, distance, comparison):
        compared = comparison == "compared"
        return {
            "instance": "C101",
            "customers": customers,
            "vehicles": vehicles,
            "distance": distance,
            "stop_reason": "time_limit",
            "comparison": comparison,
            "best_known_vehicles": 10 if customers == 100 else "",
            "best_known_distance": 828.94 if customers == 100 else "",
            "vehicle_gap": vehicles - 10 if compared else "",
            "distance_gap_pct": round(100 * (distance - 828.94) / 828.94, 2) if compared else "",
        }

    text = summary(
        [
            row(100, 10, 828.94, "compared"),
            row(100, 11, 900.00, "compared"),
            row(25, 3, 191.81, "no comparison"),
        ]
    )

    lines = text.splitlines()
    assert (
        "| C101 | 100 | 2 of 2 | 10 | 828.94 | 10.5 | 864.47 | 10 / 828.94 | +0 | +0.00 |" in text
    )
    assert any(
        line.startswith("| C101 | 25 | 0 of 1 | - | - | 3.0 | 191.81 | no comparison")
        for line in lines
    )
