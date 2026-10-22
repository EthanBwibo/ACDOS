"""Class demo: run the GA-ALNS solver on the 28 real pickup zones.

Not part of the app. Run from backend/:
    python demo_solve.py            (40 crew, 6 vehicles, seed 7)
    python demo_solve.py 60 8 3     (crew, vehicles, seed)

Travel time is the straight-line placeholder at 30 km/h until the Random
Forest is wired into fitness (#23).
"""

import csv
import random
import sys
from pathlib import Path

from app.solver.fitness import evaluate
from app.solver.ga import solve
from app.solver.individual import schedule
from app.solver.nearest_neighbour import nearest_neighbour
from app.solver.problem import JKIA, Pickup, Point, Problem, Vehicle, haversine_travel_time

ZONES_CSV = Path(__file__).resolve().parent.parent / "data" / "pickup_zones.csv"
SEATS = 14


def clock(sec: float) -> str:
    """Seconds after midnight as HH:MM."""
    minutes = int(round(sec / 60))
    return f"{minutes // 60 % 24:02d}:{minutes % 60:02d}"


def build_problem(n_crew: int, n_vehicles: int, rng: random.Random):
    with ZONES_CSV.open(newline="", encoding="utf-8") as f:
        zones = [
            (row["zone"].split(",")[0], Point(float(row["lat"]), float(row["lon"])))
            for row in csv.DictReader(f)
        ]
    names, pickups = {}, []
    for k in range(n_crew):
        zone, point = rng.choice(zones)
        # Report times between 05:00 and 09:00, on the quarter hour.
        report = 5 * 3600 + rng.randrange(0, 17) * 900
        pickups.append(Pickup(id=f"C{k + 1:02d}", location=point, deadline=report, service_sec=120))
        names[f"C{k + 1:02d}"] = zone
    vehicles = tuple(
        Vehicle(id=f"V{v + 1}", capacity=SEATS, start=JKIA, available_from=3 * 3600)
        for v in range(n_vehicles)
    )
    problem = Problem(
        pickups=tuple(pickups), vehicles=vehicles, travel_time=haversine_travel_time(30.0)
    )
    return problem, names


def summary(label: str, ev) -> None:
    print(
        f"{label:<22} cost={ev.cost:>14,.0f}  vehicles={ev.vehicles_used}  "
        f"late_crew={ev.late_crew}  unassigned={ev.unassigned}  "
        f"vehicle_time={ev.travel_sec / 3600:.1f}h  waiting={ev.waiting_sec / 3600:.1f}h"
    )


def main() -> None:
    n_crew, n_vehicles, seed = (
        int(a) for a in (sys.argv[1:] + ["40", "6", "7"][len(sys.argv) - 1 :])
    )
    rng = random.Random(seed)
    problem, names = build_problem(n_crew, n_vehicles, rng)
    print(f"{n_crew} crew, {n_vehicles} vehicles x {SEATS} seats, 28 Nairobi zones -> JKIA\n")

    summary("Nearest neighbour", evaluate(problem, nearest_neighbour(problem)))
    result = solve(problem, rng, time_limit_sec=20.0, no_improvement_generations=10)
    summary("GA-ALNS", result.evaluation)
    print(
        f"\nStopped: {result.stop_reason.value} after {result.generations} generations, "
        f"{result.history[-1].elapsed_sec:.1f}s"
    )
    for g in result.history[:: max(1, len(result.history) // 8)] + (result.history[-1],):
        print(f"  gen {g.generation:>4}  best={g.best_cost:>14,.0f}  mean={g.mean_cost:>16,.0f}")

    print("\nRoutes (leave JKIA -> pickups -> JKIA):")
    for rs in schedule(problem, result.best):
        if rs.start is None:
            continue
        stops = " -> ".join(
            f"{names[problem.pickups[s.pickup_index].id]} {clock(s.arrival)}"
            + (" LATE" if s.lateness > 0 else "")
            for s in rs.stops
        )
        reports = [problem.pickups[s.pickup_index].deadline for s in rs.stops]
        vehicle = problem.vehicles[rs.vehicle_index].id
        print(f"  {vehicle} ({rs.load}/{SEATS}) leaves {clock(rs.start)} | {stops}")
        print(f"      JKIA {clock(rs.destination_arrival)}, earliest report {clock(min(reports))}")
    if result.best.unassigned:
        print("  Unassigned:", [problem.pickups[i].id for i in result.best.unassigned])


if __name__ == "__main__":
    main()
