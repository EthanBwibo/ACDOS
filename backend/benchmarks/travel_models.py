"""The solver under RF travel against the haversine stand-in (#104).

morning_wave_120 (app/solver/instances.py), the same 120 crew and 20 vans,
solved under each travel model: the straight line at 30 km/h it was built
with, and the Random Forest with the zone matrix (app/ml/travel_time.py), with
time 0 at 03:00 EAT on Wednesday 28 October 2026. Adaptive mutation, as in
#96.

Reported:
- Each solve: stop reason, generations (speed), cost and its terms.
- Cross-evaluation, the headline: the haversine plan, as the stand-in would
  have dispatched it, driven under RF travel. Crew it thinks are on time but
  who are late under RF travel, two ways:
    fixed: each van leaves when the haversine schedule says, and drives at
      RF times (what would happen on the day);
    re-timed: the same routes, with departures searched again under RF
      travel (the best those routes can do).
- Snap distances: how far each pickup, and the depot, is from the zone point
  it travels as.
- --shortlist: TIME_DEPENDENT_FULLY_COSTED_POSITIONS at 2 and 3 against
  costing every position, as #88 measured FULLY_COSTED_POSITIONS: a few
  generations under a frozen clock, the same seed, then whether the best
  plans are the same and how long each took.

- On-time rate (#210): the share of all crew on time under RF travel, for
  the RF plan and for the haversine plan (fixed and re-timed), per seed and
  over the seeds, with paired Wilcoxon tests by seed.

Run from backend/:
    python -m benchmarks.travel_models --seeds 10 --out ../docs/results/210-travel-models-10-seeds
    python -m benchmarks.travel_models --shortlist --seeds 3
"""

import argparse
import csv
import random
import statistics
import time
from datetime import datetime
from pathlib import Path

from app.ml import journey_time, travel_time, zone_matrix
from app.solver import insertion
from app.solver.fitness import evaluate
from app.solver.ga import solve
from app.solver.individual import Individual, schedule
from app.solver.instances import morning_wave_120
from app.solver.mutation import AdaptiveMutation
from app.solver.problem import Problem
from benchmarks.plain_ga import holm, wilcoxon_p, with_notes

EPOCH = datetime(2026, 10, 28, 3, 0)  # Wednesday; morning_wave's time 0 is 03:00
TIME_LIMIT_SEC = 120.0
SHORTLIST_GENERATIONS = 3
SNAP_FAR_KM = 3.0
RUN_COLUMNS = [
    "travel", "seed", "time_limit_sec", "stop_reason", "generations", "cost", "unassigned",
    "late_crew", "on_time", "lateness_sec", "vehicles_used", "travel_sec", "waiting_sec",
    "ride_excess_sec",
]  # fmt: skip


class RfTravel:
    """Builds a fresh RF travel function, with empty caches, for each solve."""

    def __init__(self) -> None:
        self.grid = journey_time.predict_grid(journey_time.load_or_train())
        self.matrix = zone_matrix.load()
        self.zones = travel_time.load_zone_points()

    def problem(self, like: Problem) -> Problem:
        travel = travel_time.rf_travel_time(self.grid, self.matrix, self.zones, EPOCH)
        return Problem(like.pickups, like.vehicles, travel, destination=like.destination)


def drive_from(problem: Problem, v: int, route: list[int], start: float) -> float:
    """When vehicle v reaches the destination, leaving at start."""
    clock, position = start, problem.vehicles[v].start
    for i in route:
        pickup = problem.pickups[i]
        clock += problem.travel_time(position, pickup.location, clock) + pickup.service_sec
        position = pickup.location
    return clock + problem.travel_time(position, problem.destination, clock)


def cross_evaluation(haversine: Problem, rf: Problem, plan: Individual) -> dict:
    """The haversine plan under RF travel: crew the stand-in thinks are on
    time, and how many of them are late with fixed departures and re-timed."""
    planned = schedule(haversine, plan)
    on_time = {s.pickup_index for r in planned for s in r.stops if s.lateness == 0}

    fixed_late: dict[int, float] = {}
    for r in planned:
        if r.start is None:
            continue
        route = [s.pickup_index for s in r.stops]
        end = drive_from(rf, r.vehicle_index, route, r.start)
        for i in route:
            if end > rf.pickups[i].deadline:
                fixed_late[i] = end - rf.pickups[i].deadline
    retimed_late = {
        s.pickup_index: s.lateness for r in schedule(rf, plan) for s in r.stops if s.lateness > 0
    }
    fixed = {i: late for i, late in fixed_late.items() if i in on_time}
    retimed = {i: late for i, late in retimed_late.items() if i in on_time}
    routed = sum(len(r.stops) for r in planned)
    return {
        "crew": len(rf.pickups),
        # #210's on-time rate: every crew member delivered on time under RF
        # travel, out of all of them (unassigned crew are not on time).
        "on_time_fixed": routed - len(fixed_late),
        "on_time_retimed": routed - len(retimed_late),
        "on_time_under_haversine": len(on_time),
        "late_fixed": len(fixed),
        "late_fixed_mean_min": statistics.mean(fixed.values()) / 60 if fixed else 0.0,
        "late_fixed_max_min": max(fixed.values()) / 60 if fixed else 0.0,
        "late_retimed": len(retimed),
        "late_retimed_max_min": max(retimed.values()) / 60 if retimed else 0.0,
        "rf_cost_of_haversine_plan": evaluate(rf, plan).cost,
    }


def snap_distances(problem: Problem, zones: dict) -> list[float]:
    places = [p.location for p in problem.pickups] + list(
        dict.fromkeys(v.start for v in problem.vehicles)
    )
    return [travel_time.nearest_zone(p, zones)[1] for p in places]


def run_row(travel: str, seed: int, problem: Problem, result) -> dict:
    e = result.evaluation
    return {
        "travel": travel, "seed": seed, "time_limit_sec": TIME_LIMIT_SEC,
        "stop_reason": result.stop_reason.value, "generations": result.generations,
        "cost": e.cost, "unassigned": e.unassigned, "late_crew": e.late_crew,
        # On time under the travel model this plan was made with.
        "on_time": len(problem.pickups) - e.late_crew - e.unassigned,
        "lateness_sec": e.lateness_sec, "vehicles_used": e.vehicles_used,
        "travel_sec": e.travel_sec, "waiting_sec": e.waiting_sec,
        "ride_excess_sec": e.ride_excess_sec,
    }  # fmt: skip


def compare(seeds: int, out: Path) -> str:
    out.mkdir(parents=True, exist_ok=True)
    rf_travel = RfTravel()
    runs, crosses = [], []
    for seed in range(1, seeds + 1):
        haversine = morning_wave_120()
        result = solve(
            haversine, random.Random(seed), time_limit_sec=TIME_LIMIT_SEC,
            mutation=AdaptiveMutation(haversine),
        )  # fmt: skip
        runs.append(run_row("haversine", seed, haversine, result))
        crosses.append(
            {"seed": seed, **cross_evaluation(haversine, rf_travel.problem(haversine), result.best)}
        )

        rf = rf_travel.problem(haversine)
        rf_result = solve(
            rf, random.Random(seed), time_limit_sec=TIME_LIMIT_SEC, mutation=AdaptiveMutation(rf)
        )
        runs.append(run_row("rf", seed, rf, rf_result))
        print(f"seed {seed}: {runs[-2]['generations']} / {runs[-1]['generations']} generations "
              f"(haversine / rf); {crosses[-1]}", flush=True)  # fmt: skip
        # After every seed, so an interrupted run keeps what it has.
        _write(out / "results.csv", runs)
        _write(out / "cross_evaluation.csv", crosses)

    snaps = snap_distances(morning_wave_120(), rf_travel.zones)
    text = _summary(runs, crosses, snaps, matrix_note(rf_travel.matrix))
    path = out / "summary.md"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(with_notes(text, old) + "\n", encoding="utf-8")
    return text


def shortlist(seeds: int, out: Path) -> str:
    """TIME_DEPENDENT_FULLY_COSTED_POSITIONS at 2 and 3 against every position."""
    out.mkdir(parents=True, exist_ok=True)
    rf_travel = RfTravel()
    rows = []
    original = insertion.TIME_DEPENDENT_FULLY_COSTED_POSITIONS
    try:
        for seed in range(1, seeds + 1):
            plans = {}
            for label, positions in (("every", None), ("2", 2), ("3", 3)):
                insertion.TIME_DEPENDENT_FULLY_COSTED_POSITIONS = positions
                problem = rf_travel.problem(morning_wave_120())
                started = time.perf_counter()
                result = solve(
                    problem, random.Random(seed), max_generations=SHORTLIST_GENERATIONS,
                    mutation=AdaptiveMutation(problem), clock=lambda: 0.0,
                )  # fmt: skip
                seconds = time.perf_counter() - started
                plans[label] = result.best
                rows.append({
                    "seed": seed, "positions": label, "generations": result.generations,
                    "seconds": round(seconds, 1), "cost": result.evaluation.cost,
                    "same_plan_as_every": result.best.routes == plans["every"].routes
                    and result.best.unassigned == plans["every"].unassigned,
                })  # fmt: skip
                print(rows[-1], flush=True)
    finally:
        insertion.TIME_DEPENDENT_FULLY_COSTED_POSITIONS = original
    _write(out / "shortlist.csv", rows)
    lines = [
        f"{SHORTLIST_GENERATIONS} generations, frozen clock, morning_wave_120 under RF travel.",
        "",
        "| Seed | Positions | Seconds | Cost | Same plan as every position |",
        "|---|---|---|---|---|",
    ]
    lines += [
        f"| {r['seed']} | {r['positions']} | {r['seconds']} | {r['cost']:.2f} "
        f"| {'yes' if r['same_plan_as_every'] else 'no'} |"
        for r in rows
    ]
    return "\n".join(lines)


def _write(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def matrix_note(matrix: zone_matrix.ZoneMatrix) -> str:
    """Which zone matrix model the pickup-to-pickup legs came from."""
    if matrix.has_morning_anchor:
        return "**Zone matrix:** three anchors, 05:00 / 07:30 / 18:00 (#106)."
    return (
        "**Zone matrix:** two anchors, 05:00 / 18:00 (#105): pickup-to-pickup legs carry its "
        "-14% morning bias."
    )


PLANS = {
    "rf": "RF plan",
    "fixed": "Haversine plan, fixed departures",
    "retimed": "Haversine plan, re-timed",
}


def on_time_by_seed(runs: list[dict], crosses: list[dict]) -> dict[int, dict[str, float]]:
    """Per seed, the % of crew on time under RF travel for each plan in PLANS."""
    rf = {r["seed"]: r for r in runs if r["travel"] == "rf"}
    return {
        c["seed"]: {
            "rf": rf[c["seed"]]["on_time"] / c["crew"] * 100,
            "fixed": c["on_time_fixed"] / c["crew"] * 100,
            "retimed": c["on_time_retimed"] / c["crew"] * 100,
        }
        for c in crosses
        if c["seed"] in rf
    }


def on_time_table(runs: list[dict], crosses: list[dict]) -> list[str]:
    """#210's headline: on-time rates under RF travel, per seed and over the
    seeds, and paired Wilcoxon tests of the RF plan against each haversine
    variant (Holm across the two)."""
    by_seed = on_time_by_seed(runs, crosses)
    lines = [
        "On time under RF travel, % of all crew (unassigned count as not on time):",
        "",
        "| Seed | " + " | ".join(PLANS.values()) + " |",
        "|---|---|---|---|",
    ]
    for seed, rates in sorted(by_seed.items()):
        lines.append(f"| {seed} | " + " | ".join(f"{rates[p]:.1f}" for p in PLANS) + " |")
    cells = []
    for p in PLANS:
        values = [rates[p] for rates in by_seed.values()]
        cells.append(f"{statistics.fmean(values):.1f} ({min(values):.1f} to {max(values):.1f})")
    lines.append("| Mean (range) | " + " | ".join(cells) + " |")

    tests = []
    for p in ("fixed", "retimed"):
        diffs = [rates["rf"] - rates[p] for rates in by_seed.values()]
        tests.append((p, diffs, wilcoxon_p(diffs)))
    adjusted = holm([p_value for *_, p_value in tests])
    lines += [
        "",
        f"RF plan minus haversine plan, paired by seed ({len(by_seed)} seeds), Wilcoxon "
        "signed-rank with Holm across the two (* below 0.05):",
        "",
        "| Against | Mean difference, points | RF plan better / tied / worse | p (Holm) |",
        "|---|---|---|---|",
    ]
    for (p, diffs, _), p_holm in zip(tests, adjusted, strict=True):
        record = f"{sum(d > 0 for d in diffs)}/{sum(d == 0 for d in diffs)}/" + str(
            sum(d < 0 for d in diffs)
        )
        star = " *" if p_holm < 0.05 else ""
        lines.append(
            f"| {PLANS[p]} | {statistics.fmean(diffs):+.1f} | {record} | {p_holm:.4f}{star} |"
        )
    return lines


def _summary(runs: list[dict], crosses: list[dict], snaps: list[float], note: str) -> str:
    lines = [
        note,
        "",
        *on_time_table(runs, crosses),
        "",
        "Cross-evaluation: the haversine plan driven under RF travel.",
        "",
        "| Seed | On time under haversine | Late under RF, fixed departures "
        "| Mean / max late (min) | Late under RF, re-timed | Max late re-timed (min) |",
        "|---|---|---|---|---|---|",
    ]
    for c in crosses:
        lines.append(
            f"| {c['seed']} | {c['on_time_under_haversine']} of {c['crew']} | {c['late_fixed']} "
            f"| {c['late_fixed_mean_min']:.1f} / {c['late_fixed_max_min']:.1f} "
            f"| {c['late_retimed']} | {c['late_retimed_max_min']:.1f} |"
        )
    lines += [
        "",
        "| Travel | Seed | Stop | Generations | Cost | Late crew | Lateness s | Vans | Travel s "
        "| Waiting s |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(runs, key=lambda r: (r["travel"], r["seed"])):
        lines.append(
            f"| {r['travel']} | {r['seed']} | {r['stop_reason']} | {r['generations']} "
            f"| {r['cost']:,.0f} | {r['late_crew']} | {r['lateness_sec']:.0f} "
            f"| {r['vehicles_used']} | {r['travel_sec']:.0f} | {r['waiting_sec']:.0f} |"
        )
    lines += [
        "",
        f"Snap distances ({len(snaps)} places: pickups and the depot): median "
        f"{statistics.median(snaps):.2f} km, max {max(snaps):.2f} km, "
        f"{sum(s > SNAP_FAR_KM for s in snaps) / len(snaps) * 100:.1f}% over {SNAP_FAR_KM:g} km.",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--shortlist", action="store_true")
    parser.add_argument("--out", type=Path, default=Path("../docs/results/104-travel-models"))
    args = parser.parse_args()
    print(shortlist(args.seeds, args.out) if args.shortlist else compare(args.seeds, args.out))


if __name__ == "__main__":
    main()
