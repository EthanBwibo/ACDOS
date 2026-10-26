"""GA-ALNS on Solomon's (1987) instances, against the best-known results (#13).

For each instance and GA seed: build the Problem (solomon.to_problem), solve
under the time limit, check the result by Solomon's rules (solomon.
check_routes, independent of the solver) and compare with SINTEF's
best-known vehicles and distance. Writes every run to results.csv as it
finishes and prints a Markdown summary.

A run is compared with the best-known only if both the solver and the checker
find it feasible (nothing unassigned, no window missed). Otherwise its row
says "infeasible". A run on fewer customers than the instance has (customers
below 100) says "no comparison": the best-knowns are for 100 customers only.

The default budget (60 s, 3 seeds) is a validation run. The results chapter
uses #14's longer, 10-seed runs.

Run from backend/:
    python -m benchmarks.solomon_harness --instances R1 RC1 C101 --seeds 3 \
        --time-limit 60 --out ../docs/results/13-solomon
"""

import argparse
import csv
import random
import statistics
import time
from collections.abc import Callable
from pathlib import Path

from app.solver.ga import solve
from benchmarks import solomon

DEFAULT_INSTANCES = ("R1", "RC1", "C101")
COLUMNS = [
    "instance", "customers", "seed", "time_limit_sec", "stop_reason", "generations",
    "vehicles", "distance", "unassigned", "lateness", "solver_feasible", "checker_feasible",
    "best_known_vehicles", "best_known_distance", "vehicle_gap", "distance_gap_pct",
    "comparison",
]  # fmt: skip


def expand(names: list[str]) -> list[str]:
    """Instance names, with a group such as "R1" or "RC1" standing for all of
    its instances in solomon_data (R101 to R112, RC101 to RC108)."""
    available = solomon.instance_names()
    expanded: list[str] = []
    for name in (n.upper() for n in names):
        if name in available:
            matches = [name]
        else:
            # "R1" is R101..R112 but not RC1xx: the group is the name minus its
            # last two digits.
            matches = [a for a in available if a[:-2] == name]
        if not matches:
            raise ValueError(f"no Solomon instance or group called {name}")
        expanded += [m for m in matches if m not in expanded]
    return expanded


def comparison_label(no_best_known: bool, solver_feasible: bool, checker_feasible: bool) -> str:
    """Whether a run may be set against the best-known: only when there is one
    for its size, and both the solver and the independent check find it
    feasible."""
    if no_best_known:
        return "no comparison"
    if solver_feasible and checker_feasible:
        return "compared"
    return "infeasible"


def distance_gap_pct(distance: float, best_known: float) -> float:
    """Percentage gap to the best-known distance, from the distance rounded to
    2 decimals as the best-knowns are: a run matching the best-known gives
    0.00, not -0.00 from the unrounded total falling just below it."""
    return round(100 * (round(distance, 2) - best_known) / best_known, 2)


def run_one(
    name: str,
    seed: int,
    time_limit_sec: float,
    customers: int | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> dict:
    """Solve one instance with one seed and return its results row."""
    instance = solomon.load(name, customers)
    problem = solomon.to_problem(instance)
    result = solve(problem, random.Random(seed), time_limit_sec=time_limit_sec, clock=clock)
    e = result.evaluation
    check = solomon.check_routes(instance, solomon.routes_as_customers(problem, result.best.routes))

    solver_feasible = e.unassigned == 0 and e.lateness_sec == 0
    best = solomon.best_known().get(instance.name)
    comparison = comparison_label(
        instance.truncated or best is None, solver_feasible, check.feasible
    )
    compared = comparison == "compared"
    return {
        "instance": instance.name,
        "customers": len(instance.customers),
        "seed": seed,
        "time_limit_sec": time_limit_sec,
        "stop_reason": result.stop_reason.value,
        "generations": result.generations,
        "vehicles": check.vehicles,
        "distance": round(check.distance, 2),
        "unassigned": e.unassigned,
        "lateness": round(e.lateness_sec, 2),
        "solver_feasible": solver_feasible,
        "checker_feasible": check.feasible,
        "best_known_vehicles": best.vehicles if best and not instance.truncated else "",
        "best_known_distance": best.distance if best and not instance.truncated else "",
        "vehicle_gap": check.vehicles - best.vehicles if compared else "",
        "distance_gap_pct": distance_gap_pct(check.distance, best.distance) if compared else "",
        "comparison": comparison,
    }


def run(
    instances: list[str], seeds: int, time_limit_sec: float, customers: int | None, out: Path
) -> list[dict]:
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    with (out / "results.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for name in instances:
            for seed in range(1, seeds + 1):
                row = run_one(name, seed, time_limit_sec, customers)
                rows.append(row)
                # Written as it goes, so a long run interrupted keeps its rows.
                writer.writerow(row)
                fh.flush()
                print(
                    f"{row['instance']} seed {seed}: {row['vehicles']} vehicles, "
                    f"{row['distance']:.2f}, {row['comparison']}, {row['stop_reason']} "
                    f"after {row['generations']} generations",
                    flush=True,
                )
    return rows


def summary(rows: list[dict]) -> str:
    """Per instance and size: the best run (fewest vehicles, then shortest
    distance) among those compared, the means over all runs, and the
    best-known. Truncated runs get rows of their own, never mixed with the
    100-customer ones."""
    lines = [
        "| Instance | Customers | Runs compared | Best NV | Best TD | Mean NV | Mean TD | "
        "Best-known NV / TD | NV gap | TD gap % | Stops |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, size in dict.fromkeys((r["instance"], r["customers"]) for r in rows):
        runs = [r for r in rows if (r["instance"], r["customers"]) == (name, size)]
        compared = [r for r in runs if r["comparison"] == "compared"]
        stops = ", ".join(sorted({r["stop_reason"] for r in runs}))
        mean_nv = statistics.mean(r["vehicles"] for r in runs)
        mean_td = statistics.mean(r["distance"] for r in runs)
        first = runs[0]
        known = (
            f"{first['best_known_vehicles']} / {first['best_known_distance']:.2f}"
            if first["best_known_vehicles"] != ""
            else "no comparison"
        )
        if compared:
            best = min(compared, key=lambda r: (r["vehicles"], r["distance"]))
            cells = (
                f"{best['vehicles']} | {best['distance']:.2f} | {mean_nv:.1f} | {mean_td:.2f} | "
                f"{known} | {best['vehicle_gap']:+d} | {best['distance_gap_pct']:+.2f} |"
            )
        else:
            cells = f"- | - | {mean_nv:.1f} | {mean_td:.2f} | {known} | - | - |"
        lines.append(f"| {name} | {size} | {len(compared)} of {len(runs)} | {cells} {stops} |")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--instances", nargs="+", default=list(DEFAULT_INSTANCES))
    parser.add_argument("--seeds", type=int, default=3)
    parser.add_argument("--time-limit", type=float, default=60.0)
    parser.add_argument(
        "--customers", type=int, default=None, help="keep only customers 1 to n (default: all)"
    )
    parser.add_argument("--out", type=Path, default=Path("../docs/results/13-solomon"))
    args = parser.parse_args()
    rows = run(expand(args.instances), args.seeds, args.time_limit, args.customers, args.out)
    print(summary(rows))


if __name__ == "__main__":
    main()
