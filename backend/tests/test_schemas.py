"""Guards against the Pydantic models drifting from the database schema.

Reads the SQL in backend/migrations/ directly, so a column or CHECK value
changed in a migration but not in app/models/schemas.py fails here. Columns
added by a later alter table count, and a CHECK replaced there counts as its
latest version.
"""

import re
from enum import StrEnum
from pathlib import Path

import pytest
from pydantic import BaseModel

from app.models import schemas

MIGRATIONS = Path(__file__).resolve().parents[1] / "migrations"

TABLE_MODELS: dict[str, type[BaseModel]] = {
    "profiles": schemas.Profile,
    "crew_members": schemas.CrewMember,
    "vehicles": schemas.Vehicle,
    "optimization_jobs": schemas.OptimizationJob,
    "optimization_job_pickups": schemas.OptimizationJobPickup,
    "pickup_requests": schemas.PickupRequest,
    "routes": schemas.Route,
    "route_nodes": schemas.RouteNode,
    "pickup_events": schemas.PickupEvent,
    "trip_records": schemas.TripRecord,
    "pickup_zones": schemas.PickupZone,
}

# (table, column) -> enum that must hold exactly the CHECK constraint's values
CHECKED_ENUMS: dict[tuple[str, str], type[StrEnum]] = {
    ("profiles", "role"): schemas.ProfileRole,
    ("vehicles", "status"): schemas.VehicleStatus,
    ("optimization_jobs", "trigger_type"): schemas.OptimizationTriggerType,
    ("optimization_jobs", "status"): schemas.OptimizationJobStatus,
    ("optimization_job_pickups", "outcome"): schemas.JobPickupOutcome,
    ("pickup_requests", "request_type"): schemas.PickupRequestType,
    ("pickup_requests", "status"): schemas.PickupRequestStatus,
    ("routes", "status"): schemas.RouteStatus,
    ("pickup_events", "event_type"): schemas.PickupEventType,
    ("pickup_events", "exception_type"): schemas.PickupExceptionType,
}

COLUMN_TYPES = r"(uuid|text|int|smallint|numeric|timestamptz|geography)\b"


def migrations_sql() -> str:
    return "\n".join(p.read_text() for p in sorted(MIGRATIONS.glob("*.sql")))


def create_table_sql(table: str) -> str:
    """The body of `create table public.<table> (...);` from the migrations."""
    match = re.search(rf"create table public\.{table} \((.*?)\n\);", migrations_sql(), re.DOTALL)
    assert match, f"no create table for {table} in {MIGRATIONS}"
    return match.group(1)


def alter_table_sql(table: str) -> list[str]:
    """Every `alter table public.<table> ...;` statement, in migration order."""
    return re.findall(rf"alter table public\.{table}\b(.*?);", migrations_sql(), re.DOTALL)


def columns(table: str) -> set[str]:
    body = create_table_sql(table)
    found = set(re.findall(rf"^\s+([a-z_]+)\s+{COLUMN_TYPES}", body, re.MULTILINE))
    for statement in alter_table_sql(table):
        found |= set(re.findall(rf"add column ([a-z_]+)\s+{COLUMN_TYPES}", statement))
    return found


@pytest.mark.parametrize("table", TABLE_MODELS)
def test_model_fields_match_table_columns(table):
    found = {name for name, _ in columns(table)}
    assert set(TABLE_MODELS[table].model_fields) == found


@pytest.mark.parametrize(("table", "column"), CHECKED_ENUMS)
def test_enum_values_match_check_constraint(table, column):
    sql = "\n".join([create_table_sql(table), *alter_table_sql(table)])
    matches = re.findall(rf"check \({column} in \(([^)]*)\)\)", sql)
    assert matches, f"no CHECK ({column} in (...)) on {table}"
    # A later migration that replaces the CHECK wins.
    allowed = set(re.findall(r"'([a-z_]+)'", matches[-1]))
    assert {e.value for e in CHECKED_ENUMS[(table, column)]} == allowed
