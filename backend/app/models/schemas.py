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


class LeftOutReason(StrEnum):
    """Why a job left out a van it was given (van reuse across waves)."""

    # The van has a route starting after the job's wave, which it keeps.
    LATER_ROUTE = "later_route"


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
    # A driver's number, +2547XXXXXXXX (#255). Never read from the table by a
    # signed-in user: only through private.driver_contact (migration 036).
    phone: str | None = None
    created_at: datetime


class CrewMember(BaseModel):
    id: UUID
    profile_id: UUID | None = None  # null until the crew member has an app account
    name: str
    role: str  # free text in the schema (e.g. pilot, cabin_crew)
    home_location: GeoPoint
    staff_no: str | None = None  # the airline's staff number; null before #229's import
    # +2547XXXXXXXX (#255), from the roster import. Only through
    # private.crew_phone (migration 036).
    phone: str | None = None
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


class OptimizationJobLeftOutVehicle(BaseModel):
    """A van a job was given but left out, and the route that kept it out."""

    optimization_job_id: UUID
    vehicle_id: UUID
    reason: LeftOutReason
    route_id: UUID
    route_departure: datetime
    route_arrival: datetime
    created_at: datetime


class PickupRequest(BaseModel):
    id: UUID
    crew_member_id: UUID
    pickup_location: GeoPoint
    report_time: datetime  # hard deadline at JKIA
    request_type: PickupRequestType
    status: PickupRequestStatus
    # Add pickup's retry key and body hash (#253); null for other pickups.
    idempotency_key: str | None = None
    request_hash: str | None = None
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


class LeftOutVehicle(BaseModel):
    """A ticked van the job left out, e.g. "KDX 004 left out: has the
    08:00-10:00 route". route_departure and route_arrival are the later
    route's, as they were when the job was accepted."""

    vehicle_id: UUID
    plate_number: str
    reason: LeftOutReason
    route_departure: datetime
    route_arrival: datetime


class OptimisationJobResult(BaseModel):
    """A job and, once completed, its plan. Every requested pickup is in a
    route; the late ones are also in late, and the rest in unassigned, so a
    missed deadline is always listed, never left to be noticed. left_out is
    known when the job is accepted, so it is there in every status."""

    id: UUID
    status: OptimizationJobStatus
    error: str | None = None
    routes: list[PlannedRoute] = []
    late: list[LatePickup] = []
    unassigned: list[UUID] = []
    left_out: list[LeftOutVehicle] = []


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
    # For the Call button (#255): the crew member's number, +2547XXXXXXXX,
    # only from 30 minutes before scheduled_pickup until the pickup is
    # confirmed, missed or cancelled, and only with one on record. Null
    # otherwise: the number is not in the response outside that window.
    crew_phone: str | None = None


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
    # The van's driver (#255): first name once a route plans the pickup, and
    # number, +2547XXXXXXXX, only from 30 minutes before scheduled_pickup
    # until it is confirmed, missed or cancelled. Null otherwise.
    driver_first_name: str | None = None
    driver_phone: str | None = None
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


# The read-only profile screens (#231). The name is not here: the app
# already has it from profiles.


class CrewMe(BaseModel):
    # crew_members.role, free text (e.g. cabin_crew); null for a crew account
    # not yet linked to a crew_members row, like home_zone.
    crew_role: str | None
    # The pickup zone nearest the home location, by PostGIS. Never the
    # coordinates: crew get none.
    home_zone: str | None


class DriverVehicle(BaseModel):
    plate_number: str
    capacity: int = Field(gt=0)  # seats
    status: VehicleStatus


class DriverMe(BaseModel):
    vehicle: DriverVehicle | None  # null when no van is assigned to the driver


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


# Add pickup and Set home without a CSV (#253). Both reject what the roster
# import rejects, for the same reasons: the 422 ErrorBody's code is the
# import's RejectReason value (outside_pickup_zones, report_time_past,
# duplicate_pickup). No no_pickup_location: every stored crew member has a
# home (crew_members.home_location is not null).


class LatLon(BaseModel):
    """A point the dispatcher dropped on the map, in decimal degrees."""

    lat: float = Field(ge=-90, le=90)
    lon: float = Field(ge=-180, le=180)


class NearestZone(BaseModel):
    """GET /pickup-zones/nearest: the pin's nearest pickup zone, by PostGIS,
    as the import's zone check sees it. Asked once per pin placement, not
    while dragging."""

    zone_label: str
    distance_km: float  # to 0.1 km
    # Within 10 km of a zone: the point can be saved. Otherwise POST
    # /pickup-requests and PATCH .../home reject it as outside_pickup_zones.
    within_pickup_zones: bool


class CrewListItem(BaseModel):
    """One crew member in the dispatcher's Crew list and Add pickup search."""

    id: UUID
    staff_no: str | None  # null for crew added before staff numbers (#246)
    name: str
    crew_role: str
    home: LatLon  # rounded as on the driver's route
    home_zone_label: str | None  # the home's nearest pickup zone; null only without zones


class CrewListPage(BaseModel):
    items: list[CrewListItem]
    next_cursor: str | None


class PickupRequestCreate(BaseModel):
    """A pickup added by hand. Starts no re-plan."""

    crew_member_id: UUID
    report_time: AwareDatetime  # the deadline at JKIA, with its UTC offset
    request_type: PickupRequestType = PickupRequestType.ROSTERED
    # Where to collect them; left out or null means their home location.
    pickup_location: LatLon | None = None


class CrewHome(BaseModel):
    """A crew member's home after PATCH /crew-members/{id}/home."""

    id: UUID
    home: LatLon
    zone_label: str  # the new home's nearest pickup zone
    distance_km: float  # from that zone, to 0.1 km


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


# Roster CSV import (#229). The CSV format is in docs/roster_import.md.


class RejectReason(StrEnum):
    INVALID_ROW = "invalid_row"  # a field is missing or unreadable; detail says which
    OUTSIDE_PICKUP_ZONES = "outside_pickup_zones"  # over 10 km from every pickup zone
    REPORT_TIME_PAST = "report_time_past"
    DUPLICATE_PICKUP = "duplicate_pickup"  # same staff_no and report_time, in the file or stored
    # A new crew member with no pickup_location on any row: no home to use (#245).
    NO_PICKUP_LOCATION = "no_pickup_location"
    # set_home=yes on a row with no pickup_location: no point to move home to.
    SET_HOME_NEEDS_LOCATION = "set_home_needs_location"


class RejectedRow(BaseModel):
    line: int  # the line in the file; the header is line 1
    staff_no: str | None  # null when the row has none
    reason: RejectReason
    detail: str  # for people, e.g. "report_time: needs a UTC offset, e.g. +03:00"


class RowLocation(BaseModel):
    """Where a row's pickup_location is, for the dispatcher to check before
    importing (#245). Only rows that give a location have one."""

    line: int
    staff_no: str
    zone_label: str  # the nearest of the pickup zones, by PostGIS
    distance_km: float  # from that zone, to 0.1 km; over 10 is outside_pickup_zones


class HomeMove(BaseModel):
    """A set_home=yes row that moves a crew member's home_location, from its
    report time on: from the home in effect just before (stored, or an
    earlier move) to the row's point. Zones are the nearest to each point,
    by PostGIS."""

    line: int
    staff_no: str
    from_zone: str
    to_zone: str
    distance_km: float  # from the old home to the new one, to 0.1 km
    takes_effect: datetime  # the row's report time: later pickups use the new home


class HomeUse(BaseModel):
    """A row with no pickup_location: the home it is collected from, the one
    in effect at its report time."""

    line: int
    staff_no: str
    zone_label: str  # the zone nearest that home
    # The report time of the set_home row that made it the home; null for the
    # stored home (or a new crew member's first point).
    since: datetime | None


class RosterImportResult(BaseModel):
    """What an import did, or with dry_run what it would do. Rejected rows
    are skipped; the rest are imported together."""

    dry_run: bool
    rows: int  # data rows in the file, rejected ones included
    crew_created: int  # staff numbers not seen before
    crew_updated: int  # staff numbers already known: name and role refreshed
    pickups_created: int  # one per accepted row, status pending
    rows_rejected: int
    rejected: list[RejectedRow]  # in line order
    # Every row read with a pickup_location, rejected ones included, in line
    # order. Empty in results stored before #245.
    locations: list[RowLocation] = Field(default_factory=list)
    # Crew whose home a set_home=yes row moved, each move, and the home each
    # accepted row with no location uses. 0 and empty in results stored
    # before set_home.
    homes_updated: int = 0
    home_moves: list[HomeMove] = Field(default_factory=list)  # in line order
    home_uses: list[HomeUse] = Field(default_factory=list)  # accepted rows only
