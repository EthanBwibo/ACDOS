"""One optimisation, run inside a solver process (#51).

The API hands run() plain data and gets plain data back, because both cross
a process boundary and must pickle. A Problem cannot: its travel time is a
closure. So the Problem is built here, in the solver process, and only ids,
coordinates and times travel between the processes.

Solver time is seconds from the epoch: when the job left the queue and the
vans may start leaving the depot.
"""

import math
import os
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from app.jobs.processes import Process
from app.ml import journey_time, zone_matrix
from app.ml.travel_time import load_zone_points, rf_travel_time
from app.solver.ga import solve
from app.solver.individual import Individual, schedule
from app.solver.instances import BOARDING_SEC, SPEED_KMH
from app.solver.problem import (
    Pickup,
    Point,
    Problem,
    TravelTimeFn,
    Vehicle,
    haversine_travel_time,
)

# Nairobi time, which the Random Forest's hours are in. A fixed offset, not
# ZoneInfo("Africa/Nairobi"): Kenya has no daylight saving, and Windows has
# no time zone database without the tzdata package.
EAT = timezone(timedelta(hours=3), "EAT")

TRAVEL_MODELS = ("rf", "haversine")

# What the RF travel time is built from, loaded by init() once per solver
# process. Not at import: on Windows every pool process starts by importing
# this module afresh (spawn), and the API process imports it too.
_rf_inputs = None


@dataclass(frozen=True)
class PickupInput:
    id: str  # pickup_requests.id
    location: Point
    report_time: datetime  # the deadline at JKIA, timezone-aware


@dataclass(frozen=True)
class VehicleInput:
    id: str  # vehicles.id
    capacity: int


@dataclass(frozen=True)
class SolveInput:
    pickups: tuple[PickupInput, ...]
    vehicles: tuple[VehicleInput, ...]
    # Every vehicle starts here, free to leave at the epoch (docs/schema.md:
    # vehicles have no location; a config constant until #113).
    depot: Point
    epoch: datetime  # timezone-aware
    time_limit_sec: float
    travel_model: str  # one of TRAVEL_MODELS
    seed: int


@dataclass(frozen=True)
class PlannedStop:
    pickup_id: str
    arrival: datetime  # at the pickup, the ETA crew see


@dataclass(frozen=True)
class PlannedRoute:
    vehicle_id: str
    stops: tuple[PlannedStop, ...]


@dataclass(frozen=True)
class SolveOutcome:
    # Only vehicles that are used; stops in visiting order.
    routes: tuple[PlannedRoute, ...]
    # Every routed pickup: whole seconds past its report time, 0 when on time.
    late_sec: dict[str, int]
    unassigned: tuple[str, ...]


def run(job: SolveInput) -> SolveOutcome:
    """The process pool's entry point."""
    problem = build_problem(job)
    result = solve(problem, random.Random(job.seed), time_limit_sec=job.time_limit_sec)
    return outcome(problem, result.best, job.epoch)


def build_problem(job: SolveInput) -> Problem:
    pickups = tuple(
        Pickup(
            p.id,
            p.location,
            deadline=(p.report_time - job.epoch).total_seconds(),
            service_sec=BOARDING_SEC,
        )
        for p in job.pickups
    )
    vehicles = tuple(Vehicle(v.id, v.capacity, job.depot) for v in job.vehicles)
    return Problem(pickups, vehicles, travel_time(job.travel_model, job.epoch))


def travel_time(model: str, epoch: datetime) -> TravelTimeFn:
    if model == "rf":
        # The RF's grid takes Nairobi wall-clock time, without a zone.
        if _rf_inputs is None:
            raise RuntimeError("the RF is not loaded: start the pool with init('rf')")
        return rf_travel_time(*_rf_inputs, epoch.astimezone(EAT).replace(tzinfo=None))
    if model == "haversine":
        return haversine_travel_time(speed_kmh=SPEED_KMH)
    raise ValueError(f"unknown travel model {model!r}, expected one of {TRAVEL_MODELS}")


def init(model: str) -> None:
    """The process pool's initializer: runs once in each solver process when
    it starts. Loading the RF and predicting its week of hours takes seconds,
    and every job in the process needs the same ones, so they are kept."""
    global _rf_inputs
    _exit_with(os.getppid())
    if model == "rf":
        grid = journey_time.predict_grid(journey_time.load_or_train())
        _rf_inputs = (grid, zone_matrix.load(), load_zone_points())


PARENT_CHECK_SEC = 2.0


def _exit_with(parent_pid: int) -> None:
    """Exit this solver process when the API process that started it dies.

    A graceful shutdown stops the pool itself (main.lifespan). A hard kill
    (a crash, Task Manager) skips that, and the pool's processes would run on
    without a parent, holding memory and any pipe they inherited. The next
    startup still fails the jobs they had (fail_unfinished); this makes the
    processes go too. A daemon thread, so it never keeps the process alive.
    """
    if os.name == "nt":
        # os.getppid() keeps returning a dead parent's PID on Windows, so
        # wait on a handle to the parent instead. Opening it fails if the
        # parent is already gone.
        try:
            parent = Process(parent_pid)
        except OSError:
            os._exit(0)

        def watch() -> None:
            parent.wait()
            os._exit(0)
    else:
        # The parent's death re-parents this process, which changes getppid().
        def watch() -> None:
            while os.getppid() == parent_pid:
                time.sleep(PARENT_CHECK_SEC)
            os._exit(0)

    threading.Thread(target=watch, name="exit-with-parent", daemon=True).start()


def outcome(problem: Problem, best: Individual, epoch: datetime) -> SolveOutcome:
    routes = []
    late_sec = {}
    for route in schedule(problem, best):
        if not route.stops:
            continue
        stops = []
        for stop in route.stops:
            pickup_id = problem.pickups[stop.pickup_index].id
            stops.append(PlannedStop(pickup_id, epoch + timedelta(seconds=stop.arrival)))
            # Rounded up, so a crew member late by a fraction of a second is
            # still reported late.
            late_sec[pickup_id] = math.ceil(stop.lateness)
        routes.append(PlannedRoute(problem.vehicles[route.vehicle_index].id, tuple(stops)))
    unassigned = tuple(problem.pickups[i].id for i in best.unassigned)
    return SolveOutcome(tuple(routes), late_sec, unassigned)
