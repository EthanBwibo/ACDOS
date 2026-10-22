"""Benchmark instances for comparing solver variants (#71, #14).

A morning wave: crew report between 05:00 and 09:00 EAT, picked up at random
points across Nairobi, by 14-seat vans that leave one depot from 03:00 (time
0). The fleet matches scripts/build_trip_records.py and Chapter 1: up to 20
vans of 14 seats. Straight-line travel at 30 km/h, 1 min boarding.

Seeded, so every run of a benchmark solves the same problem.
"""

import random

from app.solver.problem import Pickup, Point, Problem, Vehicle, haversine_travel_time

DEPOT = Point(-1.30, 36.80)
VAN_SEATS = 14  # VEHICLE_CAPACITY in scripts/build_trip_records.py
SPEED_KMH = 30
BOARDING_SEC = 60


def morning_wave(n_crew: int, n_vans: int, seed: int) -> Problem:
    rng = random.Random(seed)
    pickups = tuple(
        Pickup(
            f"crew{i:03d}",
            Point(rng.uniform(-1.36, -1.20), rng.uniform(36.70, 36.95)),
            # 05:00 to 09:00, with time 0 at 03:00.
            deadline=rng.uniform(2 * 3600, 6 * 3600),
            service_sec=BOARDING_SEC,
        )
        for i in range(n_crew)
    )
    vehicles = tuple(Vehicle(f"van{v:02d}", VAN_SEATS, DEPOT) for v in range(n_vans))
    return Problem(pickups, vehicles, haversine_travel_time(speed_kmh=SPEED_KMH))


def smoke_30() -> Problem:
    """30 crew, 8 vans: the smoke instance of #84 and #86 (7 seats there)."""
    return morning_wave(n_crew=30, n_vans=8, seed=2026)


def morning_wave_120() -> Problem:
    """120 crew, the full 20-van fleet."""
    return morning_wave(n_crew=120, n_vans=20, seed=2027)
