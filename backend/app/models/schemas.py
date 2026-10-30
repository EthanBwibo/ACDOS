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
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobPickupOutcome(StrEnum):
    ON_TIME = "on_time"
    LATE = "late"
    UNASSIGNED = "unassigned"


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
    idempotency_key: str | None = None  # null for jobs not made through the API
    request_hash: str | None = None
    error: str | None = None  # why a failed job failed
    finished_at: datetime | None = None
    created_at: datetime


class OptimizationJobPickup(BaseModel):
    """How one pickup request came out of one job; the only record of
    unassigned pickups, which have no route node."""

    id: UUID
    optimization_job_id: UUID
    pickup_request_id: UUID
    outcome: JobPickupOutcome
    late_sec: int | None = Field(default=None, ge=0)  # null when unassigned
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
    superseded_at: datetime | None = None  # set when a later job re-plans the pickup
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


class PickupZone(BaseModel):
    """One of the 28 pickup zones of data/pickup_zones.csv (#52)."""

    id: UUID
    label: str
    location: GeoPoint
    created_at: datetime


# Optimisation job API (#51). Shaped for the dispatcher's screen over 2G/3G:
# ids and times only; names and addresses come from tables the app reads
# already.


class OptimisationJobCreate(BaseModel):
    trigger_type: OptimizationTriggerType
    pickup_request_ids: list[UUID] = Field(min_length=1)
    vehicle_ids: list[UUID] = Field(min_length=1)


class OptimisationJobAccepted(BaseModel):
    """202 body. No status: a retried POST gets the same job back, which may
    have moved on from queued; GET says where it is."""

    id: UUID


class PlannedNode(BaseModel):
    pickup_request_id: UUID
    seq_order: int
    estimated_arrival: datetime  # at the pickup


class PlannedRoute(BaseModel):
    vehicle_id: UUID
    total_distance_km: float
    nodes: list[PlannedNode]


class LatePickup(BaseModel):
    pickup_request_id: UUID
    late_sec: int  # past report_time at JKIA


class OptimisationJobResult(BaseModel):
    """A job and, once completed, its plan. Every requested pickup is in a
    route; the late ones are also in late, and the rest in unassigned, so a
    missed deadline is always listed, never left to be noticed."""

    id: UUID
    status: OptimizationJobStatus
    error: str | None = None
    routes: list[PlannedRoute] = []
    late: list[LatePickup] = []
    unassigned: list[UUID] = []


# Driver and crew read endpoints (#52). Only what each screen shows, for
# 2G/3G. Times: scheduled_pickup is the live plan's time at the stop; eta
# stays null until live tracking can estimate it from the road.


class DriverStop(BaseModel):
    route_node_id: UUID  # what a pickup confirmation refers to
    seq_order: int
    crew_name: str
    zone_label: str | None  # nearest pickup zone; null only without zones
    scheduled_pickup: datetime
    eta: datetime | None = None
    # For the driver's navigation, rounded to 5 decimal places (about 1 m).
    # The only coordinates in these endpoints; crew get none.
    lat: float
    lon: float


class DriverRoute(BaseModel):
    route_id: UUID
    status: RouteStatus
    vehicle_plate: str
    stops: list[DriverStop]


class DriverRouteResponse(BaseModel):
    route: DriverRoute | None  # null when the driver has no active route


class RouteSummary(BaseModel):
    route_id: UUID
    status: RouteStatus
    vehicle_plate: str
    first_pickup: datetime
    stop_count: int
    total_distance_km: float


class RouteSummaryPage(BaseModel):
    items: list[RouteSummary]
    next_cursor: str | None  # pass as ?cursor= for the next page; null on the last


class CrewPickup(BaseModel):
    pickup_request_id: UUID
    status: PickupRequestStatus
    report_time: datetime  # the deadline at JKIA
    scheduled_pickup: datetime | None  # null until a route plans the pickup
    eta: datetime | None = None
    vehicle_plate: str | None  # null until a route plans the pickup


class CrewPickupResponse(BaseModel):
    pickup: CrewPickup | None  # null when nothing is coming up
