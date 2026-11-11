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

from pydantic import AwareDatetime, BaseModel, Field
from pydantic.json_schema import SkipJsonSchema

from app.errors import ErrorCode


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
    # Out of planning, but not broken down: no breakdown alert (#198).
    UNAVAILABLE = "unavailable"


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
    planned_departure: datetime
    planned_arrival: datetime
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
    # When the van is due to leave the depot and reach JKIA (#113).
    planned_departure: datetime
    planned_arrival: datetime
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
    # What the server has recorded, from any phone: picked_up or missed once
    # a pickup event is in (migration 023's trigger). A reinstalled or new
    # phone has no outbox, so this is its only record of progress (#196).
    pickup_status: PickupRequestStatus


class DriverRoute(BaseModel):
    route_id: UUID
    status: RouteStatus
    vehicle_plate: str
    planned_arrival: datetime  # when the van reaches JKIA
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


class ScheduleChangeNotice(BaseModel):
    """A re-plan changed this pickup (#53): what crew had been told, and
    what now holds. Acknowledged with POST
    /crew/me/notices/{id}/acknowledge."""

    id: UUID
    # Never scheduled: only a re-plan writes a notice.
    reason: OptimizationTriggerType
    previous_pickup_time: datetime
    new_pickup_time: datetime | None  # null when the re-plan left it unassigned
    issued_at: datetime


class CrewPickup(BaseModel):
    pickup_request_id: UUID
    status: PickupRequestStatus
    report_time: datetime  # the deadline at JKIA
    scheduled_pickup: datetime | None  # null until a route plans the pickup
    eta: datetime | None = None
    vehicle_plate: str | None  # null until a route plans the pickup
    # True while a notice for this pickup is not acknowledged; notice is the
    # latest such one, null when there is none.
    needs_ack: bool
    notice: ScheduleChangeNotice | None


class NoticeAcknowledged(BaseModel):
    id: UUID
    # When the crew member acknowledged it: the first time, on a retry too.
    acknowledged_at: datetime


class CrewPickupResponse(BaseModel):
    pickup: CrewPickup | None  # null when nothing is coming up


# Pickup-event upload (#33): a batch from the app's outbox, and what became
# of each event.


class PickupEventIn(BaseModel):
    # Made on the device, so a resent event is recognised (pickup_events.
    # idempotency_key).
    idempotency_key: str = Field(min_length=1, max_length=100)
    route_node_id: UUID
    driver_id: UUID  # must be the caller
    event_type: PickupEventType
    # Exactly when event_type is exception; checked per event.
    exception_type: PickupExceptionType | None = None
    # When it happened on the device (stored as pickup_events.confirmed_at),
    # with its UTC offset.
    occurred_at: AwareDatetime


class PickupEventBatch(BaseModel):
    events: list[PickupEventIn] = Field(min_length=1, max_length=50)


class PickupEventOutcome(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"  # already stored: counts as success
    REJECTED = "rejected"  # final: retrying will not help


class PickupEventResult(BaseModel):
    idempotency_key: str
    status: PickupEventOutcome
    # The stored pickup_events.id, when accepted or duplicate (for a
    # duplicate, the event already stored), so the outbox can keep the
    # server's id.
    event_id: UUID | SkipJsonSchema[None] = None
    # Only when rejected.
    code: ErrorCode | SkipJsonSchema[None] = Field(
        default=None,
        json_schema_extra={
            "x-error-codes": [
                "validation_failed",
                "driver_mismatch",
                "idempotency_key_reused",
                "not_your_stop",
                "already_confirmed",
            ]
        },
    )
    detail: str | SkipJsonSchema[None] = None
    # Only (true) when accepted on a stop a later plan replaced: the event
    # happened before the re-plan. Tell the dispatcher (#113).
    stop_replanned: bool | SkipJsonSchema[None] = None


class PickupEventResults(BaseModel):
    results: list[PickupEventResult]  # one per event, in request order


# The dispatcher's dashboard (#136, for Android #27). Lists are keyset
# paginated like /drivers/me/routes: pass next_cursor back as ?cursor=.


class DispatcherPickup(BaseModel):
    id: UUID
    crew_name: str
    zone_label: str | None  # nearest pickup zone; null only without zones
    # For the dispatcher's route map, rounded as on the driver's route.
    lat: float
    lon: float
    report_time: datetime  # the deadline at JKIA
    status: PickupRequestStatus
    # A schedule-change notice (#53) the crew member has not acknowledged, on a
    # pickup still pending or assigned: the same rule as CrewPickup.needs_ack.
    needs_ack: bool
    # When the crew member acknowledged the latest notice; null with no
    # notices, or while the latest is not acknowledged.
    acknowledged_at: datetime | None


class DispatcherPickupPage(BaseModel):
    items: list[DispatcherPickup]
    next_cursor: str | None


class DispatcherVehicle(BaseModel):
    id: UUID
    plate_number: str
    capacity: int
    status: VehicleStatus
    # Away on a route that has departed, not yet due back at JKIA (#113):
    # a job that includes this van gets 409 vehicles_on_departed_routes.
    on_the_road: bool


class DispatcherVehiclePage(BaseModel):
    items: list[DispatcherVehicle]
    next_cursor: str | None


class DispatcherRoute(PlannedRoute):
    """#51's route shape, with the route's id and its van's plate. Live
    stops only."""

    route_id: UUID
    vehicle_plate: str


class DispatcherRoutePage(BaseModel):
    items: list[DispatcherRoute]
    next_cursor: str | None


class PickupReportTimeUpdate(BaseModel):
    """A flight delay (or any roster change) recorded for one pickup. It
    never starts a re-plan: the dispatcher does that with POST
    /optimisation-jobs."""

    report_time: AwareDatetime


class VehicleStatusUpdate(BaseModel):
    status: VehicleStatus


# Crew-to-dispatcher preset messages (#54). No free text anywhere: a message
# names a preset by its code.


class PresetMessage(BaseModel):
    code: str  # what POST /messages or POST /messages/{id}/replies takes
    label: str  # what the screens show


class PresetMessageList(BaseModel):
    items: list[PresetMessage]  # the fixed set, in code order: no pages


class CrewMessageCreate(BaseModel):
    preset_code: str = Field(min_length=1, max_length=64)


class MessageReplyCreate(BaseModel):
    preset_code: str = Field(min_length=1, max_length=64)


class MessageReply(BaseModel):
    id: UUID
    preset_code: str
    label: str
    sent_at: datetime


class CrewMessage(BaseModel):
    id: UUID
    crew_member_id: UUID
    crew_name: str
    preset_code: str
    label: str
    sent_at: datetime
    read_at: datetime | None  # null until the dispatcher has read it
    replies: list[MessageReply]  # the dispatcher's, oldest first


class CrewMessagePage(BaseModel):
    items: list[CrewMessage]  # newest first
    next_cursor: str | None


class CrewMessageRead(BaseModel):
    id: UUID
    # When the dispatcher first read it: the same on a retry.
    read_at: datetime
