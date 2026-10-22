"""Uniform vs adaptive operator selection (#71), on both benchmark instances.

For each instance and GA seed, solve once with UniformMutation and once with
AdaptiveMutation, under the same budget. Writes every run to results.csv and
the adaptive weights per segment to weights_<instance>_seed<n>.csv, and
prints a Markdown summary.

The time limits (30 s and 120 s) are benchmark budgets that let both methods
search for the same time; they are not the dispatcher's re-optimisation time.

Run from backend/:
    python -m benchmarks.operator_selection --seeds 5 --out ../docs/results/71-operator-selection
"""

import argparse
import csv
import random
import statistics
from collections.abc import Callable
from pathlib import Path

from app.solver.ga import solve
from app.solver.instances import morning_wave_120, smoke_30
from app.solver.mutation import AdaptiveMutation, UniformMutation, write_operator_log
from app.solver.problem import Problem

INSTANCES: dict[str, tuple[Callable[[], Problem], float]] = {
    "smoke_30": (smoke_30, 30.0),
    "morning_wave_120": (morning_wave_120, 120.0),
}
METHODS = {"uniform": UniformMutation, "adaptive": AdaptiveMutation}
COLUMNS = [
    "instance", "method", "seed", "time_limit_sec", "stop_reason", "generations",
    "cost", "unassigned", "late_crew", "lateness_sec", "buffer_used_sec",
    "vehicles_used", "travel_sec", "waiting_sec",
]  # fmt: skip


def run(seeds: int, out: Path) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for instance, (build, time_limit) in INSTANCES.items():
        for seed in range(1, seeds + 1):
            for method, mutation_class in METHODS.items():
                problem = build()
                mutation = mutation_class(problem)
                result = solve(
                    problem, random.Random(seed), time_limit_sec=time_limit, mutation=mutation
                )
                e = result.evaluation
                rows.append(
                    {
                        "instance": instance, "method": method, "seed": seed,
                        "time_limit_sec": time_limit, "stop_reason": result.stop_reason.value,
                        "generations": result.generations, "cost": e.cost,
                        "unassigned": e.unassigned, "late_crew": e.late_crew,
                        "lateness_sec": e.lateness_sec, "buffer_used_sec": e.buffer_used_sec,
                        "vehicles_used": e.vehicles_used, "travel_sec": e.travel_sec,
                        "waiting_sec": e.waiting_sec,
                    }
                )  # fmt: skip
                print(
                    f"{instance} seed {seed} {method}: cost {e.cost:,.0f}, "
                    f"{result.generations} generations, {result.stop_reason.value}",
                    flush=True,
                )
                if isinstance(mutation, AdaptiveMutation):
                    write_operator_log(mutation.log, out / f"weights_{instance}_seed{seed}.csv")
    with (out / "results.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return rows


def summary(rows: list[dict]) -> str:
    lines = [
        "| Instance | Method | Mean cost | SD | Best | Worst | Mean generations | Stops |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for instance in INSTANCES:
        for method in METHODS:
            runs = [r for r in rows if r["instance"] == instance and r["method"] == method]
            costs = [r["cost"] for r in runs]
            stops = sorted({r["stop_reason"] for r in runs})
            lines.append(
                f"| {instance} | {method} | {statistics.mean(costs):,.0f} | "
                f"{statistics.stdev(costs) if len(costs) > 1 else 0:,.0f} | {min(costs):,.0f} | "
                f"{max(costs):,.0f} | {statistics.mean(r['generations'] for r in runs):.1f} | "
                f"{', '.join(stops)} |"
            )
    lines += ["", "Paired by seed, adaptive minus uniform (negative: adaptive cheaper):", ""]
    for instance in INSTANCES:
        by = {(r["method"], r["seed"]): r["cost"] for r in rows if r["instance"] == instance}
        seeds = sorted({seed for _, seed in by})
        diffs = [by[("adaptive", s)] - by[("uniform", s)] for s in seeds]
        wins = sum(d < 0 for d in diffs)
        per_seed = ", ".join(f"seed {s}: {d:+,.0f}" for s, d in zip(seeds, diffs, strict=True))
        lines.append(f"- {instance}: {per_seed}; adaptive cheaper on {wins} of {len(diffs)}")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, default=5)
    parser.add_argument("--out", type=Path, default=Path("../docs/results/71-operator-selection"))
    args = parser.parse_args()
    print(summary(run(args.seeds, args.out)))


if __name__ == "__main__":
    main()
