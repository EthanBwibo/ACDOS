"""Pydantic models for the core tables in docs/schema.md (Chapter 4, Table 4.1).

Field names and enum values match the database exactly, so a row maps onto a
model without renaming. docs/schema.md is the source of truth; if a model
disagrees with it, the model is wrong. tests/test_schemas.py checks the enum
values against the CHECK constraints in backend/migrations/.

Endpoint request and response bodies that need a different shape (nested
routes, trimmed fields for 2G/3G) are defined next to these, not by changing
them.
"""

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str


class GeoPoint(BaseModel):
    """API form of a GEOGRAPHY(Point, 4326) column."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)


# Enums: values are the lowercase strings in the schema's CHECK constraints.


class ProfileRole(StrEnum):
    DISPATCHER = "dispatcher"
    DRIVER = "driver"
    CREW = "crew"


class VehicleStatus(StrEnum):
    AVAILABLE = "available"
    IN_SERVICE = "in_service"
    BROKEN_DOWN = "broken_down"


class OptimizationTriggerType(StrEnum):
    SCHEDULED = "scheduled"
    FLIGHT_DELAY = "flight_delay"
    STANDBY_ACTIVATION = "standby_activation"
    VEHICLE_BREAKDOWN = "vehicle_breakdown"


class OptimizationJobStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class PickupRequestType(StrEnum):
    ROSTERED = "rostered"
    STANDBY = "standby"


class PickupRequestStatus(StrEnum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    PICKED_UP = "picked_up"
    MISSED = "missed"
    CANCELLED = "cancelled"


class RouteStatus(StrEnum):
    ACTIVE = "active"
    COMPLETED = "completed"
    SUPERSEDED = "superseded"


class PickupEventType(StrEnum):
    PICKUP_CONFIRMED = "pickup_confirmed"
    EXCEPTION = "exception"


class PickupExceptionType(StrEnum):
    NO_SHOW = "no_show"
    VEHICLE_ISSUE = "vehicle_issue"
    TRAFFIC_DELAY = "traffic_delay"


# Tables


class Profile(BaseModel):
    """One per Supabase Auth user; id is auth.users.id."""

    id: UUID
    role: ProfileRole
    full_name: str
    created_at: datetime


class CrewMember(BaseModel):
    id: UUID
    profile_id: UUID | None = None  # null until the crew member has an app account
    name: str
    role: str  # free text in the schema (e.g. pilot, cabin_crew)
    home_location: GeoPoint
    created_at: datetime


class Vehicle(BaseModel):
    id: UUID
    assigned_driver_id: UUID | None = None
    plate_number: str
    capacity: int = Field(gt=0)
    status: VehicleStatus
    created_at: datetime


class OptimizationJob(BaseModel):
    id: UUID
    triggered_at: datetime
    trigger_type: OptimizationTriggerType
    status: OptimizationJobStatus
    created_at: datetime


class PickupRequest(BaseModel):
    id: UUID
    crew_member_id: UUID
    pickup_location: GeoPoint
    report_time: datetime  # hard deadline at JKIA
    request_type: PickupRequestType
    status: PickupRequestStatus
    created_at: datetime


class Route(BaseModel):
    id: UUID
    vehicle_id: UUID
    optimization_job_id: UUID
    total_distance_km: float
    status: RouteStatus
    created_at: datetime


class RouteNode(BaseModel):
    id: UUID
    route_id: UUID
    pickup_request_id: UUID
    seq_order: int
    estimated_arrival: datetime
    created_at: datetime


class PickupEvent(BaseModel):
    id: UUID
    route_node_id: UUID
    driver_id: UUID
    event_type: PickupEventType
    exception_type: PickupExceptionType | None = None
    confirmed_at: datetime
    synced_at: datetime | None = None  # null until synchronised
    idempotency_key: str
    created_at: datetime


class TripRecord(BaseModel):
    """One completed pickup leg, the unit the Random Forest learns from."""

    id: UUID
    route_node_id: UUID
    vehicle_id: UUID
    crew_count: int
    pickup_timestamp: datetime
    scheduled_report_time: datetime
    actual_arrival: datetime
    actual_duration_sec: int
    day_of_week: int = Field(ge=0, le=6)  # 0 = Monday, as datetime.weekday()
    route_corridor: str
    created_at: datetime
