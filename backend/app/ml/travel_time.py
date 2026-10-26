"""The solver's travel time from the Random Forest and the zone matrix (#104,
part of #23).

    to JKIA                     the Random Forest (journey_time.HourlyGrid)
    between two zones           the zone matrix (zone_matrix.ZoneMatrix.leg)
    within one zone             zone_matrix.ZoneMatrix.same_zone

The solver works in seconds after an epoch it does not know the date of
(problem.py); rf_travel_time is given the epoch, so it can turn a departure
into the weekday and hour the models need.

Places become zones: each point is snapped to the nearest of the 28 pickup
zones. The models only know zones, and pickup_requests store a point.

Travel time depends on the departure time, so the function is never marked
ignores_departure_time (Problem would freeze one hour's times for the whole
solve, #85). It is continuous in the departure time, so leaving later
does not arrive earlier unless the time falls faster than the clock (FIFO,
#12): the RF between its knots at h:30, the matrix linear in Layer 2, which
is linear between whole hours.

Every lookup is cached per function, and a function is built per solve, so
no cache outlives its solve (#85):
- RF: the week of hourly predictions, made in one predict() call (predict_grid).
- Matrix: a pair's leg at each whole hour of the week, filled the first time
  the pair is asked for. A leg is linear in the Layer 2 values (c is), and
  Layer 2 is sampled at whole hours, so the leg is linear between whole hours
  and interpolating the cached hours gives exactly what ZoneMatrix.leg would.
- Points: the zone of each Point object, and the straight line between two
  points in the same zone.
"""

import csv
import math
from datetime import datetime
from pathlib import Path

from app.ml import journey_time, zone_matrix
from app.ml.journey_time import HOURS_PER_WEEK, HourlyGrid
from app.ml.zone_matrix import ZoneMatrix
from app.solver.problem import JKIA, Point, TravelTimeFn, haversine_km

PICKUP_ZONES_CSV = journey_time.DATA_DIR / "pickup_zones.csv"


def load_zone_points(path: Path = PICKUP_ZONES_CSV) -> dict[str, Point]:
    with path.open(newline="", encoding="utf-8") as f:
        return {
            row["zone"]: Point(float(row["lat"]), float(row["lon"])) for row in csv.DictReader(f)
        }


def nearest_zone(point: Point, zones: dict[str, Point]) -> tuple[str, float]:
    """The zone whose point is closest, and how far it is in km.

    Haversine, not PostGIS: it runs inside the solver, once per place per
    solve, in memory (CLAUDE.md allows it there)."""
    return min(((zone, haversine_km(point, at)) for zone, at in zones.items()), key=lambda z: z[1])


def week_hour(epoch: datetime) -> float:
    """Hours from Monday 00:00 to epoch."""
    return epoch.weekday() * 24 + epoch.hour + epoch.minute / 60 + epoch.second / 3600


def rf_travel_time(
    grid: HourlyGrid,
    matrix: ZoneMatrix,
    zones: dict[str, Point],
    epoch: datetime,
    destination: Point = JKIA,
) -> TravelTimeFn:
    """Seconds from origin to dest leaving at depart_sec after epoch (naive,
    Nairobi time). To the destination (JKIA) by the RF; otherwise both places
    are snapped to zones. Routes never leave the destination, but Problem's
    leg tables have a row for it, so as an origin it is snapped like any
    other place."""
    if set(grid.zones) != set(zones) or set(matrix.zones) != set(zones):
        raise ValueError("the RF, the zone matrix and the zone points must cover the same zones")
    start_hour = week_hour(epoch)
    rf_hours = {
        zone: [grid.seconds(zone, 0, k + 0.5) for k in range(HOURS_PER_WEEK)] for zone in zones
    }
    matrix_hours: dict[tuple[str, str], list[float]] = {}
    same_zone_hours: dict[str, list[float]] = {}
    # Point identity -> (point, its zone, whether it is the destination).
    # Keeps the point, so its id cannot be reused while the entry exists.
    zone_of: dict[int, tuple[Point, str, bool]] = {}
    km_between: dict[tuple[int, int], tuple[Point, Point, float]] = {}

    def snapped(point: Point) -> tuple[str, bool]:
        entry = zone_of.get(id(point))
        if entry is None or entry[0] is not point:
            entry = (point, nearest_zone(point, zones)[0], point == destination)
            zone_of[id(point)] = entry
        return entry[1], entry[2]

    def km(a: Point, b: Point) -> float:
        entry = km_between.get((id(a), id(b)))
        if entry is None or entry[0] is not a or entry[1] is not b:
            entry = (a, b, haversine_km(a, b))
            km_between[(id(a), id(b))] = entry
        return entry[2]

    def travel_time(origin: Point, dest: Point, depart_sec: float) -> float:
        hour = (start_hour + depart_sec / 3600) % HOURS_PER_WEEK
        o = snapped(origin)[0]
        d, to_destination = snapped(dest)
        if to_destination:
            return _between(rf_hours[o], hour - 0.5)  # RF knots at h:30
        if o != d:
            values = matrix_hours.get((o, d))
            if values is None:
                values = [matrix.leg(o, d, 0, k) for k in range(HOURS_PER_WEEK)]
                matrix_hours[(o, d)] = values
            return _between(values, hour)
        per_km = same_zone_hours.get(o)
        if per_km is None:
            per_km = [matrix.same_zone(o, 1.0, 0, k) for k in range(HOURS_PER_WEEK)]
            same_zone_hours[o] = per_km
        return _between(per_km, hour) * km(origin, dest)

    # Lets Problem build a table of legs at time 0 to rank insertion positions
    # by (insertion._positions_worth_costing); the full costing still uses
    # the times at the real departure.
    travel_time.ranks_detours_at_start = True  # type: ignore[attr-defined]
    return travel_time


def _between(values: list[float], x: float) -> float:
    """Linear between values[k] at hour k of the week and values[k + 1],
    round the week (x may be just below 0)."""
    k = math.floor(x)
    frac = x - k
    return values[k % HOURS_PER_WEEK] * (1 - frac) + values[(k + 1) % HOURS_PER_WEEK] * frac


def load(epoch: datetime) -> TravelTimeFn:
    """The travel time from the data in data/: the cached RF (trained if
    needed), the zone matrix and the zone points."""
    model = journey_time.load_or_train()
    return rf_travel_time(
        journey_time.predict_grid(model), zone_matrix.load(), load_zone_points(), epoch
    )
