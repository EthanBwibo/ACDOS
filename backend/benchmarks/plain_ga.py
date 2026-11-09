"""Plain GA against GA-ALNS (#203), and #71's adaptive against uniform.

Three mutations in the same GA (encoding, population, crossover and
nearest-neighbour seed are shared):
- ga_alns: the solver as shipped, AdaptiveMutation (Shaw, random or worst
  removal, then greedy re-insertion, chosen adaptively).
- plain_ga: ClassicMutation, one swap or relocate on the giant tour.
- uniform: UniformMutation, the same destroy-and-repair with no adaptation.

Equal time: only the time limit ends a run. Early stopping and the generation
cap are off for every method, so each one searches for the whole budget.
Generations completed are recorded, to show what each method did with it.

Pairing: the population is built from the seed before any mutation runs, so the
same seed gives every method the same starting population. The order of the
methods alternates by seed, so neither always runs first.

Statistics (Wilcoxon signed-rank, two-sided, on the differences; zero
differences dropped, as in Wilcoxon's original test):
- per instance: over the paired seeds, with Holm's correction across the
  instances, separately for each metric;
- overall (plain GA against GA-ALNS only): across the instance means, with
  cost and distance as a percentage of GA-ALNS's mean, since instances differ
  in scale. #71's comparison has only two instances, so it has no overall test.

Results are written as they finish. A run that is interrupted can be picked up
with the same command plus --resume.

Run from backend/ (about 7 h 50 min, on a quiet machine):
    python -m benchmarks.plain_ga --seeds 10 --out ../docs/results/203-plain-ga
"""

import argparse
import csv
import random
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from scipy import stats

from app.solver.ga import solve
from app.solver.instances import morning_wave_120, smoke_30
from app.solver.mutation import AdaptiveMutation, ClassicMutation, UniformMutation
from app.solver.problem import Problem
from benchmarks import solomon, solomon_harness

SOLOMON_LIMIT_SEC = 60.0
CREW_INSTANCES: dict[str, tuple[Callable[[], Problem], float]] = {
    "morning_wave_120": (morning_wave_120, 120.0),
    "smoke_30": (smoke_30, 30.0),
}
METHODS = {"ga_alns": AdaptiveMutation, "plain_ga": ClassicMutation, "uniform": UniformMutation}
# Larger than any run reaches, so only the time limit stops one.
NO_LIMIT = 10**9
COLUMNS = [
    "instance", "method", "seed", "time_limit_sec", "elapsed_sec", "stop_reason", "generations",
    "cost", "vehicles", "distance", "late_crew", "lateness", "unassigned", "every_pickup_once",
    "checker_feasible",
]  # fmt: skip
# All lower is better. (metric, whether the overall test uses % of GA-ALNS's mean)
METRICS = {"cost": True, "vehicles": False, "distance": True, "late_crew": False}


@dataclass(frozen=True)
class Run:
    instance: str
    method: str
    seed: int
    time_limit_sec: float


def plan(seeds: int, scale: float = 1.0) -> list[Run]:
    """Every run: GA-ALNS against the plain GA on R1, RC1 and morning_wave_120;
    uniform added on morning_wave_120 and smoke_30 for #71 (GA-ALNS is the
    adaptive side there too)."""
    groups: list[tuple[str, tuple[str, ...], float]] = [
        (name, ("ga_alns", "plain_ga"), SOLOMON_LIMIT_SEC)
        for name in solomon_harness.expand(["R1", "RC1"])
    ]
    wave_limit, smoke_limit = CREW_INSTANCES["morning_wave_120"][1], CREW_INSTANCES["smoke_30"][1]
    groups.append(("morning_wave_120", ("ga_alns", "plain_ga", "uniform"), wave_limit))
    groups.append(("smoke_30", ("ga_alns", "uniform"), smoke_limit))
    return [
        Run(name, method, seed, limit * scale)
        for name, methods, limit in groups
        for seed in range(1, seeds + 1)
        for method in (methods if seed % 2 else methods[::-1])
    ]


def _crew_distance_km(problem: Problem, routes: list[list[int]]) -> float:
    """Straight-line km of the routes: start, stops in order, then JKIA."""
    total = 0.0
    for vehicle, route in zip(problem.vehicles, routes, strict=True):
        if route:
            places = [problem.pickups[i].location for i in route]
            stops = [vehicle.start, *places, problem.destination]
            total += sum(map(problem.distance, stops, stops[1:]))
    return total


def run_one(run: Run) -> dict:
    is_crew = run.instance in CREW_INSTANCES
    instance = None if is_crew else solomon.load(run.instance)
    problem = CREW_INSTANCES[run.instance][0]() if is_crew else solomon.to_problem(instance)
    result = solve(
        problem,
        random.Random(run.seed),
        time_limit_sec=run.time_limit_sec,
        max_generations=NO_LIMIT,
        no_improvement_generations=NO_LIMIT,
        mutation=METHODS[run.method](problem),
    )
    e = result.evaluation
    placed = [i for route in result.best.routes for i in route] + result.best.unassigned
    if is_crew:
        vehicles, distance, checker_feasible = (
            e.vehicles_used,
            _crew_distance_km(problem, result.best.routes),
            "",
        )
    else:
        check = solomon.check_routes(
            instance, solomon.routes_as_customers(problem, result.best.routes)
        )
        vehicles, distance, checker_feasible = check.vehicles, check.distance, check.feasible
    return {
        "instance": run.instance,
        "method": run.method,
        "seed": run.seed,
        "time_limit_sec": run.time_limit_sec,
        "elapsed_sec": round(result.history[-1].elapsed_sec, 2),
        "stop_reason": result.stop_reason.value,
        "generations": result.generations,
        "cost": e.cost,
        "vehicles": vehicles,
        "distance": round(distance, 2),
        "late_crew": e.late_crew,
        "lateness": round(e.lateness_sec, 2),
        "unassigned": e.unassigned,
        "every_pickup_once": sorted(placed) == list(range(len(problem.pickups))),
        "checker_feasible": checker_feasible,
    }


def run_all(runs: list[Run], out: Path, resume: bool, solve_run=run_one) -> list[dict]:
    """Solve every run not already in results.csv, appending as each finishes."""
    out.mkdir(parents=True, exist_ok=True)
    path = out / "results.csv"
    done = load_results(path) if resume and path.exists() else []
    finished = {(r["instance"], r["method"], r["seed"]) for r in done}
    with path.open("a" if done else "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        if not done:
            writer.writeheader()
        for run in runs:
            if (run.instance, run.method, run.seed) in finished:
                continue
            row = solve_run(run)
            writer.writerow(row)
            fh.flush()  # so an interrupted run keeps its rows
            done.append(row)
            print(
                f"{row['instance']} {row['method']} seed {row['seed']}: cost {row['cost']:,.0f}, "
                f"{row['vehicles']} vehicles, {row['generations']} generations",
                flush=True,
            )
    return done


def load_results(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    for r in rows:
        r["seed"], r["generations"] = int(r["seed"]), int(r["generations"])
        r["vehicles"], r["late_crew"] = int(r["vehicles"]), int(r["late_crew"])
        r["cost"], r["distance"] = float(r["cost"]), float(r["distance"])
    return rows


def wilcoxon_p(differences: list[float]) -> float:
    """Two-sided signed-rank p value. 1.0 when every difference is zero."""
    nonzero = [d for d in differences if d != 0]
    return float(stats.wilcoxon(nonzero, alternative="two-sided").pvalue) if nonzero else 1.0


def holm(p_values: list[float]) -> list[float]:
    """Holm's step-down adjusted p values, in the order given."""
    m = len(p_values)
    adjusted = [0.0] * m
    running_max = 0.0
    for rank, index in enumerate(sorted(range(m), key=lambda k: p_values[k])):
        running_max = max(running_max, (m - rank) * p_values[index])
        adjusted[index] = min(1.0, running_max)
    return adjusted


def paired(rows: list[dict], instance: str, metric: str, a: str, b: str) -> list[float]:
    """a minus b per seed, for the seeds both have."""
    by = {(r["method"], r["seed"]): r[metric] for r in rows if r["instance"] == instance}
    seeds = sorted({s for m, s in by if m == a} & {s for m, s in by if m == b})
    return [by[(a, s)] - by[(b, s)] for s in seeds]


def _mean(rows: list[dict], instance: str, method: str, metric: str) -> float:
    return statistics.fmean(
        r[metric] for r in rows if r["instance"] == instance and r["method"] == method
    )


def _star(p: float) -> str:
    return f"{p:.4f}{' *' if p < 0.05 else ''}"


def _record(diffs: list[float]) -> str:
    """How often method b was better, tied and worse (a minus b above 0: b better)."""
    return f"{sum(d > 0 for d in diffs)}/{sum(d == 0 for d in diffs)}/{sum(d < 0 for d in diffs)}"


def comparison_tables(rows: list[dict], instances: list[str], a: str, b: str) -> list[str]:
    """Means, generations and per-instance tests of a against b, b being GA-ALNS."""
    lines = [
        f"| Instance | Cost {a} | Cost {b} | Vans {a} | Vans {b} | Distance {a} | Distance {b} "
        f"| Late {a} | Late {b} | Generations {a} | Generations {b} |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name in instances:
        cells = [
            f"{_mean(rows, name, method, 'cost'):,.0f}" for method in (a, b)
        ] + [
            f"{_mean(rows, name, method, metric):.{digits}f}"
            for metric, digits in (("vehicles", 1), ("distance", 1), ("late_crew", 1))
            for method in (a, b)
        ] + [f"{_mean(rows, name, method, 'generations'):.0f}" for method in (a, b)]  # fmt: skip
        lines.append(f"| {name} | {' | '.join(cells)} |")

    adjusted = {
        metric: holm([wilcoxon_p(paired(rows, name, metric, a, b)) for name in instances])
        for metric in METRICS
    }
    lines += [
        "",
        f"Wilcoxon signed-rank on {a} minus {b} per seed, Holm-adjusted across "
        f"{len(instances)} instances within each metric (* below 0.05). "
        f"Wins: {b} better / tied / worse, on cost.",
        "",
        "| Instance | Cost wins | Cost p | Vans p | Distance p | Late p |",
        "|---|---|---|---|---|---|",
    ]
    for k, name in enumerate(instances):
        cells = " | ".join(_star(adjusted[metric][k]) for metric in METRICS)
        lines.append(f"| {name} | {_record(paired(rows, name, 'cost', a, b))} | {cells} |")
    return lines


def overall_table(rows: list[dict], instances: list[str], a: str, b: str) -> list[str]:
    lines = [
        f"Across the {len(instances)} instance means ({a} minus {b}). Cost and distance as a "
        f"% of {b}'s mean, vans and late crew in their own units. Above 0: {b} is better.",
        "",
        f"| Metric | Median difference | {b} better / tied / worse | p |",
        "|---|---|---|---|",
    ]
    for metric, as_percentage in METRICS.items():
        diffs = []
        for name in instances:
            mean_b = _mean(rows, name, b, metric)
            diff = _mean(rows, name, a, metric) - mean_b
            diffs.append(diff / mean_b * 100 if as_percentage else diff)
        unit = "%" if as_percentage else ""
        lines.append(
            f"| {metric} | {statistics.median(diffs):+.2f}{unit} | {_record(diffs)} | "
            f"{_star(wilcoxon_p(diffs))} |"
        )
    return lines


def summary(rows: list[dict]) -> str:
    plain = list(dict.fromkeys(r["instance"] for r in rows if r["method"] == "plain_ga"))
    uniform = list(dict.fromkeys(r["instance"] for r in rows if r["method"] == "uniform"))
    seeds = len({r["seed"] for r in rows})
    infeasible = [
        r for r in rows if r["every_pickup_once"] != "True" or r["checker_feasible"] == "False"
    ]
    return "\n".join(
        [
            f"{len(rows)} runs, {seeds} seeds per instance and method. Only the time limit "
            "ends a run: early stopping and the generation cap are off for every method.",
            f"Runs with a pickup lost or duplicated, or that Solomon's check rejects: "
            f"{len(infeasible)}.",
            "",
            "**Plain GA against GA-ALNS.**",
            "",
            *comparison_tables(rows, plain, "plain_ga", "ga_alns"),
            "",
            *overall_table(rows, plain, "plain_ga", "ga_alns"),
            "",
            "**#71: uniform against adaptive (GA-ALNS).** The adaptive runs on "
            "morning_wave_120 are the GA-ALNS runs above.",
            "",
            *comparison_tables(rows, uniform, "uniform", "ga_alns"),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--out", type=Path, default=Path("../docs/results/203-plain-ga"))
    parser.add_argument("--resume", action="store_true", help="keep the rows in results.csv")
    parser.add_argument("--summary-only", action="store_true", help="only rebuild summary.md")
    parser.add_argument("--scale", type=float, default=1.0, help="multiply every time limit")
    args = parser.parse_args()

    if not args.summary_only:
        run_all(plan(args.seeds, args.scale), args.out, args.resume)
    # Read back from the file, so a fresh run and a rebuild give the same text.
    text = summary(load_results(args.out / "results.csv"))
    (args.out / "summary.md").write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
