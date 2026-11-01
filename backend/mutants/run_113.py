"""Mutation check for #113's tests. DO NOT MERGE: runs on a throwaway CI tree.

Each mutant takes out one piece of the re-plan behaviour. The tests named
for it must then fail; if they all pass, the mutant survived and the tests
do not cover that piece. Run from backend/ with DATABASE_URL set:

    python mutants/run_113.py          # every mutant
    python mutants/run_113.py --check  # only check each mutant applies

Each file is restored from git after its mutant, so run it only in a tree
with nothing uncommitted.
"""

import subprocess
import sys
from pathlib import Path

STORE = "app/jobs/store.py"
ROUTER = "app/routers/optimisation_jobs.py"
T = "tests/test_replan_postgres.py::"
RECHECK = "conflicts = await _route_conflicts(conn, requested, vans, now, breakdown, self._grace)"


def skip(field: str) -> str:
    """The commit's re-check, then that list of conflicts emptied."""
    indent = "\n            "
    return f"{RECHECK}{indent}conflicts = __import__('dataclasses').replace(conflicts, {field}=[])"


# (name, file, original text, mutant text, tests that must fail)
MUTANTS = [
    (
        "commit does not re-check vans on the road",
        STORE,
        RECHECK,
        skip("on_the_road"),
        [T + "test_a_van_whose_plan_changed_while_the_job_ran_fails_it[left]"],
    ),
    (
        "commit does not re-check broken-down vans",
        STORE,
        RECHECK,
        skip("broken_down"),
        [T + "test_a_van_whose_plan_changed_while_the_job_ran_fails_it[broke_down]"],
    ),
    (
        "commit does not re-check collected pickups",
        STORE,
        RECHECK,
        skip("not_plannable"),
        [T + "test_a_pickup_collected_while_the_job_ran_fails_the_commit"],
    ),
    (
        "commit does not re-check pickups left behind (a van given a route)",
        STORE,
        RECHECK,
        skip("left_behind"),
        [T + "test_a_van_whose_plan_changed_while_the_job_ran_fails_it[given_a_route]"],
    ),
    (
        "a requested van's live route is not replaced",
        STORE,
        """    union
    select r.id
    from public.routes r
    where r.vehicle_id = any($3::uuid[])
      and r.status = 'active'
      and not ({_DEPARTED_ROUTE})
""",
        """    union
    select r.id
    from public.routes r
    where r.vehicle_id = any($3::uuid[])
      and false
      and not ({_DEPARTED_ROUTE})
""",
        [
            T + "test_a_van_with_a_live_route_ends_with_exactly_one_active_route[assigned]",
            T + "test_a_van_with_a_live_route_ends_with_exactly_one_active_route[cancelled]",
        ],
    ),
    (
        "the commit checks only the vans the plan uses",
        STORE,
        "        vans = vehicle_ids\n",
        "        vans = [UUID(route.vehicle_id) for route in outcome.routes]\n",
        [T + "test_a_van_whose_plan_changed_while_the_job_ran_fails_it[unused_van_given_a_route]"],
    ),
    (
        "commit re-checks nothing",
        STORE,
        "            if conflicts:\n                raise RouteConflictError(conflicts)",
        "            if False:\n                raise RouteConflictError(conflicts)",
        [
            T + "test_a_van_whose_plan_changed_while_the_job_ran_fails_it[left]",
            T + "test_a_van_whose_plan_changed_while_the_job_ran_fails_it[broke_down]",
            T + "test_a_pickup_collected_while_the_job_ran_fails_the_commit",
            T + "test_a_van_whose_plan_changed_while_the_job_ran_fails_it[given_a_route]",
        ],
    ),
    (
        "a route has not departed at its planned departure",
        STORE,
        "    or r.planned_departure <= $2\n    or exists",
        # $2 stays in the text, so the queries that use it only here still
        # know its type.
        "    or (r.planned_departure <= $2 and false)\n    or exists",
        [T + "test_a_route_has_departed_once_its_van_was_due_to_leave"],
    ),
    (
        "a van is free at its planned arrival, no grace",
        STORE,
        "and $2 < r.planned_arrival + $3::interval",
        "and $2 < r.planned_arrival + $3::interval * 0",
        [T + "test_a_van_on_the_road_is_refused_until_it_is_due_back"],
    ),
    (
        "a van with a pickup event is not on the road before its departure",
        STORE,
        """          r.planned_departure <= $2
          or exists (
              select 1 from public.route_nodes rn
              join public.pickup_events e on e.route_node_id = rn.id
              where rn.route_id = r.id
          )
      )
      and $2 <""",
        """          r.planned_departure <= $2
      )
      and $2 <""",
        [
            T + "test_a_van_that_left_early_is_on_the_road",
            T + "test_a_van_whose_plan_changed_while_the_job_ran_fails_it[left]",
        ],
    ),
    (
        "a broken-down van's departed route stays fixed",
        STORE,
        "    and not ($3::boolean and exists (",
        "    and not ($3::boolean and false and exists (",
        [
            T + "test_a_breakdown_replan_moves_what_the_broken_van_had_not_collected",
            T + "test_the_breakdown_route_is_superseded_once_nothing_is_left_on_it",
        ],
    ),
    (
        "a broken-down van's route is freed whatever the trigger",
        STORE,
        "    and not ($3::boolean and exists (",
        "    and not (($3::boolean or true) and exists (",
        [T + "test_a_breakdown_replan_moves_what_the_broken_van_had_not_collected"],
    ),
    (
        "a stop the broken van recorded loses its node",
        STORE,
        """                       or (n.route_id in ({_REPLACED_ROUTES})
                           and not exists (
                               select 1 from public.pickup_events e
                               where e.route_node_id = n.id
                           )))""",
        """                       or (n.route_id in ({_REPLACED_ROUTES})))""",
        [T + "test_a_breakdown_replan_moves_what_the_broken_van_had_not_collected"],
    ),
    (
        "a re-plan does not take the whole route",
        ROUTER,
        "    planned = body.pickup_request_ids + conflicts.left_behind",
        "    planned = body.pickup_request_ids",
        [T + "test_a_replan_of_one_pickup_takes_its_whole_route"],
    ),
    (
        "the API accepts a broken-down van",
        ROUTER,
        "    broken = [v.id for v in vehicles.values() if v.status == VehicleStatus.BROKEN_DOWN]",
        "    broken = []",
        [T + "test_a_broken_down_van_is_refused"],
    ),
]


def pytest(tests: list[str]) -> bool:
    """True when every test passes."""
    return (
        subprocess.run(
            [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *tests]
        ).returncode
        == 0
    )


def main() -> int:
    check_only = "--check" in sys.argv
    for name, path, old, _, _ in MUTANTS:
        count = Path(path).read_text(encoding="utf-8").count(old)
        if count != 1:
            print(f"cannot apply '{name}': its text is in {path} {count} times")
            return 2
    if check_only:
        print(f"all {len(MUTANTS)} mutants apply")
        return 0

    # Unmutated, every test named must pass, or a kill means nothing.
    named = sorted({t for *_, tests in MUTANTS for t in tests})
    if not pytest(named):
        print("baseline: a named test fails without any mutant")
        return 2

    results = []
    for name, path, old, new, tests in MUTANTS:
        file = Path(path)
        file.write_text(file.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
        try:
            killed = not pytest(tests)
        finally:
            subprocess.run(["git", "checkout", "--", path], check=True)
        results.append((name, killed))

    print("\n#113 mutation check")
    for name, killed in results:
        print(f"  {'killed  ' if killed else 'SURVIVED'}  {name}")
    survived = sum(not killed for _, killed in results)
    print(f"{len(results) - survived} of {len(results)} killed")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
