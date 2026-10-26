"""Problem data for the many-to-one CDVRPTW: what the solver is given.

Times are seconds from a planning epoch the caller chooses (for example the
start of the optimisation run). Floats keep the GA loop fast; converting to
clock time (hour of day for the Random Forest) is the travel time function's
job, not the solver's.
"""

import math
from collections.abc import Callable
from dataclasses import dataclass, field

from app.solver.weights import CREW, FitnessWeights


@dataclass(frozen=True)
class Point:
    lat: float
    lon: float


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
    # Window on the start of service at the stop (#99), for Solomon's
    # instances: a vehicle arriving before ready waits; starting after due is
    # late. Crew have none (-inf, inf): only their report time at the
    # destination matters.
    ready: float = -math.inf
    due: float = math.inf


@dataclass(frozen=True)
class Vehicle:
    id: str
    capacity: int
    # Where the vehicle is when the run starts (depot or current position).
    start: Point
    # Earliest time it can leave start.
    available_from: float = 0.0


@dataclass(frozen=True)
class LegTable:
    """Every leg time a route can use, for travel time that ignores departure
    (Problem.legs); or every leg length (Problem.leg_lengths, #99).

    Locations are numbered: pickups by their index, the destination after
    them. between[a][b] is the time from location a to b; from_start[v][b]
    from vehicle v's start to b.
    """

    between: tuple[tuple[float, ...], ...]
    from_start: tuple[tuple[float, ...], ...]
    destination: int  # index of the destination in the rows


@dataclass(frozen=True)
class Problem:
    pickups: tuple[Pickup, ...]
    vehicles: tuple[Vehicle, ...]
    travel_time: TravelTimeFn
    destination: Point = JKIA
    # What the fitness charges for (#99): crew transport by default.
    weights: FitnessWeights = CREW
    # Length of the straight line between two places: Shaw relatedness, and
    # the distance term D when weights.distance is above 0.
    distance: Callable[[Point, Point], float] = field(
        default=haversine_km, compare=False, repr=False
    )
    # Built in __post_init__ when travel time ignores departure; None
    # otherwise (the Random Forest, whose legs change with the hour).
    legs: LegTable | None = field(default=None, init=False, compare=False, repr=False)
    # Every leg's length by Problem.distance, laid out as legs. Built only
    # when weights.distance is above 0, so crew solves never pay for it.
    leg_lengths: LegTable | None = field(default=None, init=False, compare=False, repr=False)
    # True when any pickup has a finite stop window. Scheduling takes the
    # window-aware path only then, so crew solves run exactly as before.
    stop_windows: bool = field(default=False, init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        if len({p.id for p in self.pickups}) != len(self.pickups):
            raise ValueError("pickup ids must be unique")
        if len({v.id for v in self.vehicles}) != len(self.vehicles):
            raise ValueError("vehicle ids must be unique")
        if any(v.capacity <= 0 for v in self.vehicles):
            raise ValueError("vehicle capacity must be above 0")
        if any(p.demand <= 0 for p in self.pickups):
            raise ValueError("pickup demand must be above 0")
        if any(p.ready > p.due for p in self.pickups):
            raise ValueError("pickup ready must not be after due")
        if self.weights.latest_departure and any(math.isfinite(p.due) for p in self.pickups):
            # The departure search (individual._latest_start) works back from
            # the deadline at the destination only, so leaving late could push
            # a stop past its due time unnoticed. A ready time alone is safe:
            # the search accounts for the wait like any other delay.
            raise ValueError(
                "a pickup has a due time at its stop, but these weights use latest "
                "departure, which only looks at the destination deadline: use "
                "weights with latest_departure=False, such as SOLOMON"
            )
        # The dataclass is frozen, hence object.__setattr__ below.
        object.__setattr__(
            self,
            "stop_windows",
            any(math.isfinite(p.ready) or math.isfinite(p.due) for p in self.pickups),
        )
        if getattr(self.travel_time, "ignores_departure_time", False):
            # A memo made here lives as long as this Problem, so it cannot
            # grow across solves (#85).
            object.__setattr__(self, "travel_time", _remember_legs(self.travel_time))
            object.__setattr__(self, "legs", self._leg_table())
        if self.weights.distance > 0:
            object.__setattr__(self, "leg_lengths", self._leg_table(self.distance))

    def _leg_table(self, leg: Callable[[Point, Point], float] | None = None) -> LegTable:
        """Every leg, computed once: the solver reads them millions of times
        per solve, and a list lookup is cheaper than any call (#88).

        By travel time (departure ignored) unless leg gives another measure,
        such as Problem.distance for leg_lengths.
        """
        if leg is None:
            travel = self.travel_time

            def leg(a: Point, b: Point) -> float:
                return travel(a, b, 0.0)

        places = [p.location for p in self.pickups] + [self.destination]
        return LegTable(
            between=tuple(tuple(leg(a, b) for b in places) for a in places),
            from_start=tuple(tuple(leg(v.start, b) for b in places) for v in self.vehicles),
            destination=len(self.pickups),
        )


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


def urgency(pickup: Pickup) -> float:
    """The time that makes a pickup urgent: the due time at its stop when it
    has one (Solomon), else its report time. Orders the nearest-neighbour
    seeds and is Shaw's time term; for crew it is the report time, as before
    #99."""
    return pickup.due if math.isfinite(pickup.due) else pickup.deadline


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
