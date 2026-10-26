"""Solomon's (1987) VRPTW benchmark instances (#13): load one, turn it into a
Problem for the GA-ALNS solver, and check a solution by Solomon's rules.

The rules (Solomon, 1987): each customer has a demand, a service time and a
time window [ready, due] on the start of service. Vehicles of one capacity
leave the depot no earlier than it opens, wait at a customer reached before
its ready time, must start service by its due time, and must be back at the
depot by its due time (the end of the horizon). Travel time between two
points equals their Euclidean distance.

Distances are kept at full double precision, as SINTEF's best-known list
does; only reported totals are rounded, to 2 decimals (README.md).

check_routes is written from the instance data alone, not from the solver, so
the harness's totals and its feasible / infeasible verdict do not depend on
the code under test.
"""

import csv
import math
from dataclasses import dataclass
from pathlib import Path

from app.solver.problem import Pickup, Point, Problem, Vehicle
from app.solver.weights import SOLOMON

DATA_DIR = Path(__file__).parent / "solomon_data"
INSTANCES_DIR = DATA_DIR / "instances"
SOLUTIONS_DIR = DATA_DIR / "solutions"
BEST_KNOWN_CSV = DATA_DIR / "best_known.csv"

# Floating-point slack when checking times: sums of square roots taken in a
# different order can differ in the last bits.
TIME_TOLERANCE = 1e-6


@dataclass(frozen=True)
class Customer:
    number: int  # 0 is the depot
    x: float
    y: float
    demand: int
    ready: float
    due: float
    service: float


@dataclass(frozen=True)
class Instance:
    name: str  # as in the file, e.g. "R101"
    vehicles: int
    capacity: int
    depot: Customer
    customers: tuple[Customer, ...]
    # Customers in the original instance: 100, also when this one keeps fewer.
    full_size: int

    @property
    def truncated(self) -> bool:
        return len(self.customers) < self.full_size


@dataclass(frozen=True)
class BestKnown:
    vehicles: int
    distance: float
    reference: str


@dataclass(frozen=True)
class RouteCheck:
    feasible: bool
    vehicles: int
    distance: float  # full precision; round only to report
    violations: tuple[str, ...]


def load(name_or_path: str | Path, customers: int | None = None) -> Instance:
    """Read an instance in Solomon's text format.

    name_or_path is a name such as "R101" (looked up in solomon_data) or a
    path. customers=n keeps the depot and customers 1 to n, the usual way of
    making the 25- and 50-customer versions.
    """
    path = Path(name_or_path)
    if not path.exists():
        path = INSTANCES_DIR / f"{str(name_or_path).lower()}.txt"
    lines = [line.split() for line in path.read_text(encoding="ascii").splitlines()]
    lines = [tokens for tokens in lines if tokens]

    name = lines[0][0]
    # The fleet is the line of two numbers after the "NUMBER CAPACITY" heading.
    heading = next(k for k, tokens in enumerate(lines) if tokens[0] == "NUMBER")
    vehicles, capacity = (int(v) for v in lines[heading + 1])
    # Customer rows are the lines of seven numbers.
    rows = [tokens for tokens in lines if len(tokens) == 7 and all(_is_number(t) for t in tokens)]
    table = [
        Customer(
            number=int(row[0]),
            x=float(row[1]),
            y=float(row[2]),
            demand=int(row[3]),
            ready=float(row[4]),
            due=float(row[5]),
            service=float(row[6]),
        )
        for row in rows
    ]
    depot, all_customers = table[0], tuple(table[1:])
    if depot.number != 0:
        raise ValueError(f"{path}: the first customer row must be the depot (0)")
    if customers is not None:
        if not 0 < customers <= len(all_customers):
            raise ValueError(f"customers must be between 1 and {len(all_customers)}")
        kept = all_customers[:customers]
    else:
        kept = all_customers
    return Instance(name, vehicles, capacity, depot, kept, full_size=len(all_customers))


def _is_number(token: str) -> bool:
    try:
        float(token)
    except ValueError:
        return False
    return True


def euclidean(origin: Point, dest: Point) -> float:
    """Straight-line distance on Solomon's plane: x is stored in Point.lon and
    y in Point.lat (see to_problem). Full double precision."""
    return math.hypot(origin.lon - dest.lon, origin.lat - dest.lat)


def euclidean_travel_time(origin: Point, dest: Point, depart: float) -> float:
    """Solomon's travel time: equal to the distance, whenever the vehicle leaves."""
    return euclidean(origin, dest)


# Lets the Problem build its leg table once (Problem._leg_table).
euclidean_travel_time.ignores_departure_time = True  # type: ignore[attr-defined]


def _point(customer: Customer) -> Point:
    # Point holds latitude and longitude; on Solomon's plane it holds y and x.
    return Point(lat=customer.y, lon=customer.x)


def to_problem(instance: Instance) -> Problem:
    """The instance as a Problem with the SOLOMON weights.

    Each customer becomes a pickup whose stop window is its time window, and
    whose deadline at the destination is the depot's due time: every vehicle
    must be back before the horizon ends. The depot is both where vehicles
    start (no earlier than it opens) and the destination. Pickup ids are the
    customer numbers, so routes map back to the instance (routes_as_customers).
    """
    depot = _point(instance.depot)
    pickups = tuple(
        Pickup(
            id=str(c.number),
            location=_point(c),
            deadline=instance.depot.due,
            demand=c.demand,
            service_sec=c.service,
            ready=c.ready,
            due=c.due,
        )
        for c in instance.customers
    )
    vehicles = tuple(
        Vehicle(f"v{k:02d}", instance.capacity, depot, available_from=instance.depot.ready)
        for k in range(instance.vehicles)
    )
    return Problem(
        pickups,
        vehicles,
        euclidean_travel_time,
        destination=depot,
        weights=SOLOMON,
        distance=euclidean,
    )


def routes_as_customers(problem: Problem, routes: list[list[int]]) -> list[list[int]]:
    """Solver routes (pickup indices) as Solomon customer numbers."""
    return [[int(problem.pickups[i].id) for i in route] for route in routes]


def check_routes(instance: Instance, routes: list[list[int]]) -> RouteCheck:
    """Check routes of customer numbers by Solomon's rules; empty routes are
    ignored. Returns the vehicles used and the total distance, and every rule
    broken (feasible is True when there are none)."""
    by_number = {c.number: c for c in instance.customers}
    depot = instance.depot
    violations = []

    visits = [n for route in routes for n in route]
    unknown = sorted(set(visits) - set(by_number))
    if unknown:
        violations.append(f"unknown customers {unknown}")
    repeated = sorted({n for n in visits if visits.count(n) > 1})
    if repeated:
        violations.append(f"customers visited more than once {repeated}")
    missing = sorted(set(by_number) - set(visits))
    if missing:
        violations.append(f"customers not visited {missing}")

    used = [route for route in routes if route]
    if len(used) > instance.vehicles:
        violations.append(f"{len(used)} routes, but the fleet has {instance.vehicles} vehicles")

    total = 0.0
    for k, route in enumerate(used, start=1):
        stops = [by_number[n] for n in route if n in by_number]
        load = sum(c.demand for c in stops)
        if load > instance.capacity:
            violations.append(f"route {k} carries {load} > {instance.capacity}")
        clock, here = depot.ready, depot
        for c in stops:
            leg = math.hypot(c.x - here.x, c.y - here.y)
            total += leg
            start = max(clock + leg, c.ready)
            if start > c.due + TIME_TOLERANCE:
                violations.append(
                    f"route {k}: customer {c.number} starts at {start:.2f} > due {c.due:g}"
                )
            clock, here = start + c.service, c
        leg = math.hypot(depot.x - here.x, depot.y - here.y)
        total += leg
        if clock + leg > depot.due + TIME_TOLERANCE:
            violations.append(f"route {k}: back at the depot at {clock + leg:.2f} > {depot.due:g}")

    return RouteCheck(not violations, len(used), total, tuple(violations))


def read_solution(path: str | Path) -> list[list[int]]:
    """Routes from a SINTEF solution file: lines "Route k : n n n ..."."""
    routes = []
    for line in Path(path).read_text(encoding="ascii").splitlines():
        if line.strip().startswith("Route") and ":" in line:
            routes.append([int(n) for n in line.split(":", 1)[1].split()])
    return routes


def best_known() -> dict[str, BestKnown]:
    """SINTEF's best-known results (hierarchical: vehicles, then distance) for
    the 100-customer instances in solomon_data; see README.md."""
    with BEST_KNOWN_CSV.open(newline="", encoding="utf-8") as fh:
        return {
            row["instance"]: BestKnown(
                int(row["vehicles"]), float(row["distance"]), row["reference"]
            )
            for row in csv.DictReader(fh)
        }


def instance_names() -> list[str]:
    """Every instance in solomon_data, as "C101", "R101", ..."""
    return sorted(path.stem.upper() for path in INSTANCES_DIR.glob("*.txt"))
