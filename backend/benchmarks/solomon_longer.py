"""GA-ALNS on R101, R105, RC101 and RC105 at 300 s, against #203's 60 s runs (#211).

How far does the gap to the best-known solutions close with five times the
time? The runs use #203's runner (plain_ga.run_one, method ga_alns): adaptive
mutation, and only the time limit ends a run. Seeds 1 to 10, as in #203. The
solver uses time only to stop, so a 300 s run makes the same search as the
60 s run with the same seed and then carries on: each pair is one search,
stopped at 60 s and at 300 s.

Per instance, at 60 s and 300 s: mean and best vehicles (NV) and distance
(TD, from Solomon's independent check), the gap to SINTEF's best-known (NV,
and TD in %), the share of the 60 s gap that 300 s closes, generations, and
feasible runs. Wilcoxon signed-rank by seed (300 s minus 60 s) on NV and on
TD, Holm across the four instances within each.

Solomon's objective is hierarchical (fewest vehicles first), so a run with a
van fewer can have a longer distance: read TD gaps beside NV gaps.

Run from backend/:
    python -m benchmarks.solomon_longer --seeds 10 --out ../docs/results/211-solomon-300s
"""

import argparse
import statistics
from pathlib import Path

from benchmarks import plain_ga as pg
from benchmarks import solomon

INSTANCES = ["R101", "R105", "RC101", "RC105"]
LONG_SEC = 300.0
SHORT_RESULTS = (
    Path(__file__).resolve().parents[2] / "docs" / "results" / "203-plain-ga" / "results.csv"
)


def plan(seeds: int, scale: float = 1.0) -> list[pg.Run]:
    return [
        pg.Run(name, "ga_alns", seed, LONG_SEC * scale)
        for name in INSTANCES
        for seed in range(1, seeds + 1)
    ]


def short_runs(path: Path = SHORT_RESULTS) -> list[dict]:
    """#203's GA-ALNS runs on these instances."""
    return [
        r for r in pg.load_results(path) if r["method"] == "ga_alns" and r["instance"] in INSTANCES
    ]


def feasible(row: dict) -> bool:
    return row["checker_feasible"] in (True, "True") and int(row["unassigned"]) == 0


def gap_closed(short_gap: float, long_gap: float) -> str:
    """The share of the 60 s gap that 300 s removes, in %; '-' with no gap to close."""
    if short_gap <= 0:
        return "-"
    return f"{(short_gap - long_gap) / short_gap * 100:.0f}%"


def by_seed(rows: list[dict], name: str) -> dict[int, dict]:
    return {r["seed"]: r for r in rows if r["instance"] == name}


def instance_table(short: list[dict], long: list[dict]) -> list[str]:
    known = solomon.best_known()
    lines = [
        "| Instance | Best-known NV / TD | NV 60 s | NV 300 s | NV gap closed | TD 60 s "
        "| TD 300 s | TD gap % 60 s | TD gap % 300 s | Best 60 s | Best 300 s "
        "| Generations 60 / 300 | Feasible 60 / 300 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name in INSTANCES:
        best = known[name]
        s, lg = by_seed(short, name).values(), by_seed(long, name).values()
        nv = [statistics.fmean(r["vehicles"] for r in rows) for rows in (s, lg)]
        td = [statistics.fmean(r["distance"] for r in rows) for rows in (s, lg)]
        td_gap = [(d - best.distance) / best.distance * 100 for d in td]
        bests = [min(rows, key=lambda r: (r["vehicles"], r["distance"])) for rows in (s, lg)]
        gens = [statistics.fmean(r["generations"] for r in rows) for rows in (s, lg)]
        ok = [sum(feasible(r) for r in rows) for rows in (s, lg)]
        lines.append(
            f"| {name} | {best.vehicles} / {best.distance:.2f} | {nv[0]:.1f} | {nv[1]:.1f} "
            f"| {gap_closed(nv[0] - best.vehicles, nv[1] - best.vehicles)} "
            f"| {td[0]:.1f} | {td[1]:.1f} | {td_gap[0]:+.1f} | {td_gap[1]:+.1f} "
            f"| {bests[0]['vehicles']} / {bests[0]['distance']:.1f} "
            f"| {bests[1]['vehicles']} / {bests[1]['distance']:.1f} "
            f"| {gens[0]:.0f} / {gens[1]:.0f} | {ok[0]} / {ok[1]} of {len(lg)} |"
        )
    return lines


def change_table(short: list[dict], long: list[dict]) -> list[str]:
    """Wilcoxon signed-rank on 300 s minus 60 s per seed, Holm across instances."""
    diffs = {
        metric: [
            [
                long_row[metric] - by_seed(short, name)[seed][metric]
                for seed, long_row in sorted(by_seed(long, name).items())
                if seed in by_seed(short, name)
            ]
            for name in INSTANCES
        ]
        for metric in ("vehicles", "distance")
    }
    adjusted = {m: pg.holm([pg.wilcoxon_p(d) for d in ds]) for m, ds in diffs.items()}
    lines = [
        "300 s minus 60 s, paired by seed: Wilcoxon signed-rank, Holm across the four "
        "instances within each metric (* below 0.05). Better / tied / worse: 300 s's record.",
        "",
        "| Instance | NV mean change | NV better / tied / worse | NV p | TD mean change "
        "| TD better / tied / worse | TD p |",
        "|---|---|---|---|---|---|---|",
    ]
    for k, name in enumerate(INSTANCES):
        cells = []
        for metric in ("vehicles", "distance"):
            d = diffs[metric][k]
            record = f"{sum(x < 0 for x in d)}/{sum(x == 0 for x in d)}/{sum(x > 0 for x in d)}"
            cells.append(f"{statistics.fmean(d):+.2f} | {record} | {pg._star(adjusted[metric][k])}")
        lines.append(f"| {name} | {' | '.join(cells)} |")
    return lines


def summary(short: list[dict], long: list[dict]) -> str:
    return "\n".join(
        [
            f"GA-ALNS, seeds 1 to {len({r['seed'] for r in long})}, only the time limit ends a "
            "run. 60 s: #203's runs. 300 s: this issue's. NV vehicles, TD distance "
            "(Solomon's check); best-known from SINTEF.",
            "",
            *instance_table(short, long),
            "",
            *change_table(short, long),
        ]
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, default=10)
    parser.add_argument("--out", type=Path, default=Path("../docs/results/211-solomon-300s"))
    parser.add_argument("--resume", action="store_true", help="keep the rows in results.csv")
    parser.add_argument("--summary-only", action="store_true", help="only rebuild summary.md")
    parser.add_argument("--scale", type=float, default=1.0, help="multiply the time limit")
    args = parser.parse_args()

    if not args.summary_only:
        pg.run_all(plan(args.seeds, args.scale), args.out, args.resume)
    text = summary(short_runs(), pg.load_results(args.out / "results.csv"))
    path = args.out / "summary.md"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(pg.with_notes(text, old) + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
