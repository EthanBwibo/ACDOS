"""How early crew reach JKIA against how many vans, as the waiting weight rises.

The crew objective charges waiting at JKIA beyond the 15-minute buffer (W) at
the same rate as vehicle time (T), 1 per second, and each van at 3,600. So an
extra van is worth an hour of crew waiting, and the solver may collect crew
well before they need to leave (the #37 self-test: picked up at 03:24, at JKIA
04:44, reporting 06:15). This measures the trade-off without changing the
production objective: only W's weight moves (FitnessWeights.waiting), and T,
vans and every hard tier stay as in CREW. Weight 1 is CREW itself.

morning_wave_120 (120 crew, 20 vans) under RF travel, as #210 ran it, time 0 at
03:00 EAT on Wednesday 28 October 2026. Seeds 1 to N, each weight on the same
seeds, adaptive mutation, 120 s each.

The fleet is 20 vans, so a higher weight can't buy more than that; --fleets 20 30
also runs the same crew with 30 vans, to see the trade-off without that cap.

Early arrival: report time minus the van's arrival at JKIA, per crew member on
time, in minutes. The 15-minute buffer is the target, so 15 is "just right".

Run from backend/ on a quiet machine (about 31 min per fleet, 3 weights x 5 seeds):
    python -m benchmarks.waiting_tradeoff --seeds 5 --fleets 20 30 \
        --out ../docs/results/waiting-weight-tradeoff
"""

import argparse
import csv
import random
import statistics
from dataclasses import replace
from pathlib import Path

from app.ml import travel_time
from app.solver.ga import solve
from app.solver.individual import route_times
from app.solver.instances import morning_wave
from app.solver.mutation import AdaptiveMutation
from app.solver.problem import Problem
from app.solver.weights import CREW, REPORT_BUFFER_SEC
from benchmarks.plain_ga import with_notes
from benchmarks.travel_models import EPOCH, RfTravel

TIME_LIMIT_SEC = 120.0
WAITING_WEIGHTS = (1.0, 3.0, 10.0)
COLUMNS = [
    "fleet", "waiting_weight", "seed", "time_limit_sec", "stop_reason", "generations", "cost",
    "vehicles_used", "unassigned", "late_crew", "mean_early_min", "median_early_min",
    "max_early_min", "drive_h", "waiting_beyond_buffer_h",
]  # fmt: skip


def problem_for(rf: RfTravel, waiting_weight: float, fleet: int) -> Problem:
    # morning_wave_120's crew (same seed); the vans are made after the crew, so
    # the fleet size doesn't change them.
    like = morning_wave(n_crew=120, n_vans=fleet, seed=2027)
    travel = travel_time.rf_travel_time(rf.grid, rf.matrix, rf.zones, EPOCH)
    # Weight 1 is CREW exactly (waiting None), so its costs are the production ones.
    weights = CREW if waiting_weight == CREW.time else replace(CREW, waiting=waiting_weight)
    return Problem(
        like.pickups, like.vehicles, travel, destination=like.destination, weights=weights
    )


def early_minutes(problem: Problem, routes: list[list[int]]) -> list[float]:
    """Report time minus arrival at JKIA, for each crew member not late."""
    early = []
    for v, route in enumerate(routes):
        if not route:
            continue
        _, _, end = route_times(problem, v, route)
        for i in route:
            margin = problem.pickups[i].deadline - end
            if margin >= 0:
                early.append(margin / 60)
    return early


def run_row(fleet: int, weight: float, seed: int, problem: Problem, result) -> dict:
    e = result.evaluation
    early = early_minutes(problem, result.best.routes)
    return {
        "fleet": fleet, "waiting_weight": weight, "seed": seed, "time_limit_sec": TIME_LIMIT_SEC,
        "stop_reason": result.stop_reason.value, "generations": result.generations,
        "cost": e.cost, "vehicles_used": e.vehicles_used, "unassigned": e.unassigned,
        "late_crew": e.late_crew,
        "mean_early_min": statistics.fmean(early) if early else 0.0,
        "median_early_min": statistics.median(early) if early else 0.0,
        "max_early_min": max(early, default=0.0),
        "drive_h": e.travel_sec / 3600, "waiting_beyond_buffer_h": e.waiting_sec / 3600,
    }  # fmt: skip


def summary(rows: list[dict]) -> str:
    return "\n\n".join(
        f"### {fleet} vans\n\n" + fleet_summary([r for r in rows if r["fleet"] == fleet])
        for fleet in sorted({r["fleet"] for r in rows})
    )


def fleet_summary(rows: list[dict]) -> str:
    seeds = sorted({r["seed"] for r in rows})
    lines = [
        f"morning_wave_120's crew, {rows[0]['fleet']} vans, under RF travel, "
        f"seeds {seeds[0]} to {seeds[-1]}, "
        f"{TIME_LIMIT_SEC:.0f} s each. Only the waiting weight W changes; "
        "weight 1 is the production objective (CREW). "
        f"Early: minutes before report time at JKIA, crew on time; the buffer is "
        f"{REPORT_BUFFER_SEC / 60:.0f} min.",
        "",
        "| W per second | Vans used, mean (range) | Early, mean min | Early, median min | "
        "Early, max min | Late crew | Unassigned | Drive h | Waiting beyond buffer h |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for weight in WAITING_WEIGHTS:
        rs = [r for r in rows if r["waiting_weight"] == weight]
        if not rs:
            continue
        vans = [r["vehicles_used"] for r in rs]
        lines.append(
            f"| {weight:g} | {statistics.fmean(vans):.1f} ({min(vans)} to {max(vans)}) "
            f"| {statistics.fmean(r['mean_early_min'] for r in rs):.1f} "
            f"| {statistics.fmean(r['median_early_min'] for r in rs):.1f} "
            f"| {max(r['max_early_min'] for r in rs):.1f} "
            f"| {sum(r['late_crew'] for r in rs)} | {sum(r['unassigned'] for r in rs)} "
            f"| {statistics.fmean(r['drive_h'] for r in rs):.1f} "
            f"| {statistics.fmean(r['waiting_beyond_buffer_h'] for r in rs):.1f} |"
        )
    lines += [
        "",
        "Means over seeds; max early is the largest over every seed. Late crew and unassigned "
        f"are totals over the {len(seeds)} seeds. With {len(seeds)} seeds a signed-rank test "
        f"cannot go below p = {2 / 2 ** len(seeds):.4f}, so no test is reported; the per-seed "
        "rows are in results.csv.",
    ]
    return "\n".join(lines)


def _write(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--fleets", type=int, nargs="+", default=[20])
    parser.add_argument("--out", type=Path, default=Path("../docs/results/waiting-weight-tradeoff"))
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    rf = RfTravel()
    rows = []
    runs = [
        (fleet, seed, weight)
        for fleet in args.fleets
        for seed in range(1, args.seeds + 1)
        for weight in WAITING_WEIGHTS
    ]
    for fleet, seed, weight in runs:
        problem = problem_for(rf, weight, fleet)
        result = solve(
            problem, random.Random(seed), time_limit_sec=TIME_LIMIT_SEC,
            mutation=AdaptiveMutation(problem),
        )  # fmt: skip
        rows.append(run_row(fleet, weight, seed, problem, result))
        r = rows[-1]
        print(
            f"{fleet} vans, seed {seed}, W {weight:g}: {r['vehicles_used']} vans, early mean "
            f"{r['mean_early_min']:.1f} max {r['max_early_min']:.1f} min, "
            f"{r['late_crew']} late, {r['generations']} generations",
            flush=True,
        )
        _write(args.out / "results.csv", rows)  # after every run, in case of a stop

    text = summary(rows)
    path = args.out / "summary.md"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(with_notes(text, old) + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
