"""DO NOT MERGE. One-off mutation run for #33's Postgres tests (branch
mut/33-postgres). Each mutation is applied, only the tests meant to catch it
run and must FAIL (pytest exit 1), then it is reverted.

Two kinds:
- file: a change to the Python source;
- sql: a CREATE OR REPLACE of 022's or 023's function on the CI database
  (the migrations are applied before this script runs), restored from the
  migration file afterwards.
"""

import asyncio
import os
import pathlib
import re
import subprocess
import sys

import asyncpg

TESTS = "tests/test_pickup_events_postgres.py"
MIGRATIONS = pathlib.Path("migrations")


def function_ddl(migration: str) -> str:
    """The migration's function, as CREATE OR REPLACE."""
    text = (MIGRATIONS / migration).read_text()
    match = re.search(r"create function .*?\n\$\$;", text, re.DOTALL)
    assert match, migration
    return match.group(0).replace("create function", "create or replace function", 1)


HELPER = function_ddl("022_record_pickup_events_by_when_they_happened.sql")
TRIGGER = function_ddl("023_update_pickup_status_from_events.sql")
E = "app/events.py"

# (name, kind, target, original, mutated, -k expression)
MUTATIONS = [
    (
        "driver_id not checked",
        "file",
        E,
        "    if event.driver_id != driver_id:",
        "    if False:",
        "one_bad_event",
    ),
    (
        "future occurred_at allowed",
        "file",
        E,
        "    if event.occurred_at > now + FUTURE_SKEW:",
        "    if False:",
        "one_bad_event",
    ),
    (
        "exception_type not checked",
        "file",
        E,
        "    if is_exception and event.exception_type is None:",
        "    if False:",
        "one_bad_event",
    ),
    (
        "a stored key always a duplicate",
        "file",
        E,
        "    if tuple(stored)[1:] == _fields(event):",
        "    if True:",
        "idempotent or reused",
    ),
    (
        "second confirmation not mapped",
        "file",
        E,
        "            if error.constraint_name == ONE_CONFIRMATION_INDEX:",
        "            if False:",
        "confirmed_once or concurrent_confirmations",
    ),
    (
        "concurrent key not re-read",
        "file",
        E,
        "            stored = await conn.fetchrow(_STORED, event.idempotency_key)\n"
        "            if stored is None:\n"
        "                raise",
        "            raise",
        "concurrent_upload",
    ),
    (
        "stop_replanned never set",
        "file",
        E,
        "replanned=superseded_at is not None",
        "replanned=False",
        "replan",
    ),
    (
        "event_id not returned",
        "file",
        E,
        "        event_id=event_id,\n        stop_replanned=",
        "        stop_replanned=",
        "resend",
    ),
    (
        "only drivers: role check removed",
        "file",
        "app/routers/pickup_events.py",
        '    if profile is None or profile.role != "driver":',
        "    if False:",
        "only_drivers",
    ),
    (
        "022: completed routes refused",
        "sql",
        HELPER,
        "r.status in ('active', 'completed')",
        "r.status = 'active'",
        "completed",
    ),
    (
        "022: superseded-before-the-event branch removed",
        "sql",
        HELPER,
        "              or occurred < n.superseded_at\n",
        "",
        "replan or 022",
    ),
    (
        "022: superseded nodes always allowed",
        "sql",
        HELPER,
        "or occurred < n.superseded_at",
        "or n.superseded_at is not null",
        "replan or 022",
    ),
    (
        "023: missed no longer goes to picked_up",
        "sql",
        TRIGGER,
        "status in ('assigned', 'missed')",
        "status = 'assigned'",
        "status_with_guards",
    ),
    (
        "023: cancelled not guarded",
        "sql",
        TRIGGER,
        "where id = pickup and status in ('assigned', 'missed');",
        "where id = pickup;",
        "status_with_guards",
    ),
    (
        "023: no_show leaves the status",
        "sql",
        TRIGGER,
        "        set status = 'missed'\n",
        "        set status = status\n",
        "status_with_guards",
    ),
]


def execute(sql: str) -> None:
    async def run():
        conn = await asyncpg.connect(os.environ["DATABASE_URL"])
        try:
            await conn.execute(sql)
        finally:
            await conn.close()

    asyncio.run(run())


def pytest(*args: str) -> subprocess.CompletedProcess:
    command = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args]
    try:
        return subprocess.run(command, capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(command, 124, "timed out after 300 s", "")


def last_line(run: subprocess.CompletedProcess) -> str:
    return run.stdout.strip().splitlines()[-1] if run.stdout.strip() else "(no output)"


baseline = pytest(TESTS)
print("baseline:", last_line(baseline), flush=True)
if baseline.returncode != 0:
    print(baseline.stdout[-4000:])
    sys.exit(1)

failures = 0
print("| Mutation | Targeted tests | Result |")
print("|---|---|---|")
for name, kind, target, original, mutated, k in MUTATIONS:
    source = pathlib.Path(target).read_text() if kind == "file" else target
    if source.count(original) != 1:
        print(f"| {name} | `{k}` | INVALID: original not found once |")
        failures += 1
        continue
    changed = source.replace(original, mutated)
    if kind == "file":
        pathlib.Path(target).write_text(changed)
    else:
        execute(changed)
    try:
        run = pytest(TESTS, "-k", k)
    finally:
        if kind == "file":
            pathlib.Path(target).write_text(source)
        else:
            execute(source)
    verdict = {1: "CAUGHT", 0: "MISSED"}.get(run.returncode, f"INVALID (exit {run.returncode})")
    if verdict != "CAUGHT":
        failures += 1
    print(f"| {name} | `{k}` | {verdict}: {last_line(run)} |", flush=True)

after = pytest(TESTS)
print("after reverting all:", last_line(after))
sys.exit(1 if failures or after.returncode else 0)
