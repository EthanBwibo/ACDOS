"""Problem data for the many-to-one CDVRPTW: what the solver is given.

Times are seconds from a planning epoch the caller chooses (for example the
start of the optimisation run). Floats keep the GA loop fast; converting to
clock time (hour of day for the Random Forest) is the travel time function's
job, not the solver's.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float


# JKIA terminal, the single destination (docs/schema.md: a backend constant
# until a reference table is decided).
JKIA = Point(lat=-1.3192, lon=36.9278)

# Seconds to drive from origin to destination when leaving at depart_sec.
# Depends on departure time so the Random Forest (#23) can be dropped in.
TravelTimeFn = Callable[[Point, Point, float], float]


@dataclass(frozen=True)
class Pickup:
    """One crew member to collect. Maps to a pickup_requests row."""

    id: str
    location: Point
    # Latest arrival at the destination: the crew member's report time.
    deadline: float
    # Seats taken. 1 for a crew member; Solomon instances use other values.
    demand: int = 1
    # Time spent at the stop for boarding.
    service_sec: float = 0.0


@dataclass(frozen=True)
class Vehicle:
    id: str
    capacity: int
    # Where the vehicle is when the run starts (depot or current position).
    start: Point
    # Earliest time it can leave start.
    available_from: float = 0.0


@dataclass(frozen=True)
class Problem:
    pickups: tuple[Pickup, ...]
    vehicles: tuple[Vehicle, ...]
    travel_time: TravelTimeFn
    destination: Point = JKIA

    def __post_init__(self) -> None:
        if len({p.id for p in self.pickups}) != len(self.pickups):
            raise ValueError("pickup ids must be unique")
        if len({v.id for v in self.vehicles}) != len(self.vehicles):
            raise ValueError("vehicle ids must be unique")
        if any(v.capacity <= 0 for v in self.vehicles):
            raise ValueError("vehicle capacity must be above 0")
        if any(p.demand <= 0 for p in self.pickups):
            raise ValueError("pickup demand must be above 0")
        if getattr(self.travel_time, "ignores_departure_time", False):
            # A memo made here lives as long as this Problem, so it cannot
            # grow across solves (#85). The dataclass is frozen, hence setattr.
            object.__setattr__(self, "travel_time", _remember_legs(self.travel_time))


def _remember_legs(travel_time: TravelTimeFn) -> TravelTimeFn:
    """Wrap a travel time function that ignores departure time so each leg is
    computed once. The solver asks for the same few hundred legs millions of
    times per solve.

    Keyed on the identity of the two Points, which is cheaper than hashing
    them (a dataclass hash costs as much as the haversine). Each entry keeps
    both Points, so their ids cannot be reused by other objects while it
    exists, and is only used when handed those very objects.

    Not for time-dependent travel (the Random Forest): its legs change with
    the departure time; its caching is #23's.
    """
    memo: dict[tuple[int, int], tuple[Point, Point, float]] = {}

    def remembered(origin: Point, dest: Point, depart_sec: float) -> float:
        entry = memo.get((id(origin), id(dest)))
        if entry is not None and entry[0] is origin and entry[1] is dest:
            return entry[2]
        seconds = travel_time(origin, dest, depart_sec)
        memo[(id(origin), id(dest))] = (origin, dest, seconds)
        return seconds

    return remembered


def haversine_km(origin: Point, dest: Point) -> float:
    """Straight-line (great-circle) distance in km.

    Haversine instead of PostGIS because the solver uses it in memory, inside
    loops that run thousands of times per generation, where a database round
    trip per pair would be far too slow.
    """
    earth_radius_km = 6371.0
    lat1, lat2 = math.radians(origin.lat), math.radians(dest.lat)
    dlat = lat2 - lat1
    dlon = math.radians(dest.lon - origin.lon)
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * earth_radius_km * math.asin(math.sqrt(a))


def haversine_travel_time(speed_kmh: float) -> TravelTimeFn:
    """Straight-line distance at a constant speed, ignoring departure time.

    Only a placeholder until the Random Forest is wired into fitness (#23);
    also handy for tests. Marked as ignoring departure time, so a Problem
    built with it remembers each leg (_remember_legs).
    """
    metres_per_sec = speed_kmh * 1000 / 3600

    def travel_time(origin: Point, dest: Point, depart_sec: float) -> float:
        return haversine_km(origin, dest) * 1000 / metres_per_sec

    travel_time.ignores_departure_time = True  # type: ignore[attr-defined]
    return travel_time
