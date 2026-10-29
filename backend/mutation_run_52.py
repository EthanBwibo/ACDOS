"""DO NOT MERGE. One-off mutation run for #52's Postgres tests (branch
mut/52-postgres). For each mutation: apply it, run only the tests meant to
catch it, expect them to FAIL (pytest exit 1), revert. Exit 1 if any
mutation is missed, or if the unmutated baseline does not pass."""

import pathlib
import subprocess
import sys

TESTS = "tests/test_driver_crew_reads_postgres.py"

# (name, file, original, mutated, -k expression for the targeted tests)
MUTATIONS = [
    (
        "role check removed",
        "app/routers/me.py",
        "    if profile is None or profile.role != role:",
        "    if False:",
        "wrong_role_or_no_profile",
    ),
    (
        "no switch to the caller (RLS bypassed)",
        "app/reads.py",
        "        await become(conn, user_id)",
        "        pass",
        "run_as_the_caller",
    ),
    (
        "keyset condition dropped",
        "app/reads.py",
        "where $2::timestamptz is null or (first_pickup, id) > ($2, $3)",
        "where ($2::timestamptz is null or true) and ($3::uuid is null or true)",
        "paginated",
    ),
    (
        "crew filter dropped from the SQL",
        "app/reads.py",
        "        where p.crew_member_id = $1",
        "        where ($1::uuid is null or true)",
        "sql_filters_hold",
    ),
    (
        "driver filter dropped from the SQL",
        "app/reads.py",
        "    where v.assigned_driver_id = $1 and r.status = 'active'",
        "    where ($1::uuid is null or true) and r.status = 'active'",
        "sql_filters_hold",
    ),
    (
        "superseded filter dropped from the stops SQL",
        "app/reads.py",
        "    where n.route_id = $1 and n.superseded_at is null",
        "    where n.route_id = $1",
        "sql_filters_hold",
    ),
    (
        "coordinates not rounded",
        "app/reads.py",
        'lat=round(s["lat"], COORDINATE_DECIMALS),',
        'lat=s["lat"],',
        "current_route_with_live_stops",
    ),
]


def pytest(*args: str) -> subprocess.CompletedProcess:
    """A hung run (a test looping on a mutant) counts as exit 124, not a hang."""
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args]
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, "timed out after 180 s", "")


baseline = pytest(TESTS)
print("baseline:", baseline.stdout.strip().splitlines()[-1], flush=True)
if baseline.returncode != 0:
    print(baseline.stdout[-4000:])
    sys.exit(1)

failures = 0
print("| Mutation | Targeted tests | Result |")
print("|---|---|---|")
for name, path, original, mutated, target in MUTATIONS:
    file = pathlib.Path(path)
    source = file.read_text()
    if source.count(original) != 1:
        print(f"| {name} | `{target}` | INVALID: original text not found once |")
        failures += 1
        continue
    file.write_text(source.replace(original, mutated))
    try:
        run = pytest(TESTS, "-k", target)
    finally:
        file.write_text(source)
    summary = run.stdout.strip().splitlines()[-1] if run.stdout.strip() else "(no output)"
    verdict = {1: "CAUGHT", 0: "MISSED"}.get(run.returncode, f"INVALID (exit {run.returncode})")
    if verdict != "CAUGHT":
        failures += 1
    print(f"| {name} | `{target}` | {verdict}: {summary} |", flush=True)

after = pytest(TESTS)
print("after reverting all:", after.stdout.strip().splitlines()[-1])
sys.exit(1 if failures or after.returncode else 0)
