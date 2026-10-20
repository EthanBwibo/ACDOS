from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str


class GeoPoint(BaseModel):
    latitude: float
    longitude: float


class CrewRole(StrEnum):
    PILOT = "PILOT"
    CABIN_CREW = "CABIN_CREW"


class CrewMember(BaseModel):
    id: str
    name: str
    role: CrewRole
    pickup_location: GeoPoint
    duty_report_time: datetime


class PickupRequestStatus(StrEnum):
    PENDING = "PENDING"
    ASSIGNED = "ASSIGNED"
    CONFIRMED = "CONFIRMED"
    MISSED = "MISSED"


class PickupRequest(BaseModel):
    id: str
    crew_member_id: str
    pickup_location: GeoPoint
    hard_deadline: datetime
    status: PickupRequestStatus


class Vehicle(BaseModel):
    id: str
    registration: str
    seating_capacity: int


class RouteNode(BaseModel):
    id: str
    sequence_index: int
    pickup_request_id: str
    estimated_arrival_time: datetime
    actual_arrival_time: datetime | None = None


class Route(BaseModel):
    id: str
    vehicle_id: str
    nodes: list[RouteNode]
    optimization_job_id: str


class OptimizationTrigger(StrEnum):
    SCHEDULED = "SCHEDULED"
    STANDBY_ACTIVATION = "STANDBY_ACTIVATION"
    VEHICLE_BREAKDOWN = "VEHICLE_BREAKDOWN"
    FLIGHT_AMENDMENT = "FLIGHT_AMENDMENT"
    MANUAL = "MANUAL"


class OptimizationJobStatus(StrEnum):
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


class OptimizationJob(BaseModel):
    id: str
    triggered_at: datetime
    trigger: OptimizationTrigger
    resulting_routes: list[Route] = []
    status: OptimizationJobStatus


class PickupEventType(StrEnum):
    CONFIRMED = "CONFIRMED"
    EXCEPTION_FLAGGED = "EXCEPTION_FLAGGED"


class PickupEvent(BaseModel):
    id: str
    route_node_id: str
    driver_id: str
    event_type: PickupEventType
    device_local_timestamp: datetime
    synced_at: datetime | None = None


class TripRecord(BaseModel):
    id: str
    route_node_id: str
    actual_duration_seconds: int
    day_of_week: int
    hour_of_day: int
    route_corridor: str
