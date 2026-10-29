"""Where an RF solve spends its time, and what the speed-ups buy (#109).

morning_wave_120 under RF travel (travel_models.RfTravel, time 0 at 03:00
EAT on Wednesday 28 October 2026), adaptive mutation, a fresh Problem (and so
fresh caches) for every solve.

Modes:
- --profile: cProfile on one 120 s solve (seed 1); the top entries by own
  time and by cumulative time. cProfile inflates the cost of every Python
  call, so its generation count is not comparable with a plain run.
- --counters: one unprofiled 120 s solve (seed 1) with counting wrappers
  installed here (the solver code is untouched): travel calls, departure
  search steps, route costings and how many repeat a route already costed
  in the solve, positions costed per insertion.
- --fixed-generations N: seeds 1-3, stopped by N generations only, each run
  twice, the faster kept. An exact speed-up must give the very same best
  plan, so the run asserts it against the baseline recorded with
  --record-baseline, and the wall time alone measures the gain.
- --equal-time: 120 s per (seed, TIME_DEPENDENT_FULLY_COSTED_POSITIONS
  setting in --positions), settings interleaved within each seed, each run
  after a cool-down and between two probes; a seed's block is re-run if a
  run in it was not clean. Settings compared seed by seed.
- --quality N|auto: cost after N frozen-clock generations per setting (auto:
  the median generations "every" reached in the clean equal-time blocks).
- --generations-in-time: generations one 120 s solve reaches with the code
  as it is, under --travel rf or haversine (before vs after, from worktrees).

Run from backend/:
    python -m benchmarks.rf_speed --profile
    python -m benchmarks.rf_speed --counters
    python -m benchmarks.rf_speed --fixed-generations 5 --record-baseline --label main
    python -m benchmarks.rf_speed --fixed-generations 5 --label cache
    python -m benchmarks.rf_speed --equal-time --positions 2 3 none
    python -m benchmarks.rf_speed --quality auto --positions 2 3 none
    python -m benchmarks.rf_speed --generations-in-time --travel haversine --seeds 1
"""

import argparse
import collections
import cProfile
import csv
import io
import json
import pstats
import random
import statistics
import subprocess
import time
from datetime import datetime
from pathlib import Path

import app
from app.ml import travel_time
from app.solver import fitness as fitness_module
from app.solver import ga, individual, insertion, mutation, removal
from app.solver.ga import solve
from app.solver.instances import morning_wave_120
from app.solver.mutation import AdaptiveMutation
from app.solver.problem import Problem
from benchmarks.travel_models import EPOCH, RfTravel

TIME_LIMIT_SEC = 120.0
SEEDS = (1, 2, 3)
REPEATS = 2  # fixed-generations runs per seed; the faster is kept
OUT = Path("../docs/results/109-rf-solver-speed")
# The backend this file sits in. Speed-ups are measured from git worktrees, so
# the app it imports must be this tree's, not another checkout's.
BACKEND = Path(__file__).resolve().parents[1]


def provenance() -> dict:
    """Which code this process runs: the app package it imported, HEAD, and
    any uncommitted change under app/ (the solver and the travel models),
    taken just after the imports. Fails if the app is another tree's."""
    app_dir = Path(app.__file__).resolve().parent
    if app_dir != BACKEND / "app":
        raise RuntimeError(f"imported {app_dir}, not this tree's {BACKEND / 'app'}")

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], capture_output=True, text=True, check=True, cwd=BACKEND
        ).stdout

    changes = git("status", "--porcelain", "--", "app").splitlines()
    return {
        "started": datetime.now().isoformat(timespec="seconds"),
        "app": str(app_dir),
        "head": git("rev-parse", "HEAD").strip(),
        "app_clean": not changes,
        "app_changes": changes,
    }


# Module level, so it is taken when the app modules have just been imported.
PROVENANCE = provenance()


def provenance_line() -> str:
    p = PROVENANCE
    state = "clean" if p["app_clean"] else "changed: " + "; ".join(p["app_changes"])
    return f"Started {p['started']}, app {p['app']}, HEAD {p['head'][:7]}, backend/app {state}."


# The machine probe: a fixed piece of pure-Python work (about 5 s), timed
# before and after every fixed-generations solve. If it drifts, the machine
# did (heat, power state), and run time / probe time corrects for it.
PROBE_ITERATIONS = 14_000_000
# A solve whose two probes differ by more than this is flagged.
PROBE_DRIFT_FLAG = 0.10


def probe() -> float:
    """Seconds for the same pure-Python work every time; no app code."""
    started = time.perf_counter()
    x, table = 0.0, [0.0] * 1024
    for i in range(PROBE_ITERATIONS):
        x = (x * 1.000001 + table[i & 1023] + i % 7) % 1e6
        table[(i * 7) & 1023] = x
    return time.perf_counter() - started


def rf_problem(rf_travel: RfTravel, travel_wrapper=None) -> Problem:
    """morning_wave_120 under RF travel; a new Problem, so nothing cached is
    carried over from another solve. travel_wrapper, if given, wraps the
    travel function before the Problem sees it."""
    like = morning_wave_120()
    travel = travel_time.rf_travel_time(rf_travel.grid, rf_travel.matrix, rf_travel.zones, EPOCH)
    if travel_wrapper is not None:
        travel = travel_wrapper(travel)
    return Problem(like.pickups, like.vehicles, travel, destination=like.destination)


def timed_solve(problem: Problem, seed: int):
    return solve(
        problem, random.Random(seed), time_limit_sec=TIME_LIMIT_SEC,
        mutation=AdaptiveMutation(problem),
    )  # fmt: skip


def frozen_solve(problem: Problem, seed: int, generations: int):
    """Exactly `generations` generations on a frozen clock: the same plan
    on every machine and at every speed."""
    return solve(
        problem, random.Random(seed), max_generations=generations,
        no_improvement_generations=generations + 1, mutation=AdaptiveMutation(problem),
        clock=lambda: 0.0,
    )  # fmt: skip


def profile(rf_travel: RfTravel, out: Path, generations: int | None) -> str:
    """cProfile on seed 1: 120 s, or a fixed number of frozen-clock
    generations if given."""
    problem = rf_problem(rf_travel)
    profiler = cProfile.Profile()
    if generations is None:
        result = profiler.runcall(timed_solve, problem, 1)
        run = f"{TIME_LIMIT_SEC:g} s: {result.generations} generations (inflated by profiling)"
    else:
        result = profiler.runcall(frozen_solve, problem, 1, generations)
        run = f"{generations} frozen-clock generations"
    profiler.dump_stats(out / "profile.pstats")
    text = io.StringIO()
    text.write(provenance_line() + "\n")
    text.write(f"cProfile, seed 1, {run}, cost {result.evaluation.cost!r}\n")
    for order in ("tottime", "cumtime"):
        text.write(f"\n## Top 25 by {order}\n")
        pstats.Stats(profiler, stream=text).sort_stats(order).print_stats(25)
    (out / "profile.txt").write_text(text.getvalue(), encoding="utf-8")
    return text.getvalue()


class Counters:
    """Counting wrappers around the solver's hot functions, installed on the
    modules for the length of one solve (see install / remove)."""

    def __init__(self) -> None:
        self.travel_calls = 0
        self.drives = 0
        self.search_steps: list[int] = []
        # Hours from available_from to the start the search settles on.
        self.search_gap_hours: list[float] = []
        # Positions handed to the full costing, per _best_position call.
        self.positions: list[int] = []
        # Route costings by (generation, where), and how many repeat a
        # (vehicle, route) costed earlier in the solve. Generation 0 is the
        # initial population and the operators' set-up.
        self.costings: collections.Counter = collections.Counter()
        self.repeats: collections.Counter = collections.Counter()
        # Of the mutated child's routes, how many its own destroy and repair
        # had already costed (in their per-call caches).
        self.mutated_from_operators = 0
        self.generation = 0
        self._crossovers = 0
        self._fitness_calls = 0  # in this iteration
        self._seen: set = set()
        self._iteration: set = set()
        self._context = "outside the GA loop"  # set-up, the final evaluate
        self._originals: list = []

    def wrap_travel(self, travel):
        """travel, counted, with its leg functions (#109 b) counted too, so
        the Problem still times routes by them as it does uncounted."""

        def counted(origin, dest, depart_sec):
            self.travel_calls += 1
            return travel(origin, dest, depart_sec)

        counted.ranks_detours_at_start = getattr(travel, "ranks_detours_at_start", False)
        leg_function = getattr(travel, "leg_function", None)
        if leg_function is not None:

            def counted_leg_function(origin, dest):
                leg = leg_function(origin, dest)

                def counted_leg(depart_sec):
                    self.travel_calls += 1
                    return leg(depart_sec)

                return counted_leg

            counted.leg_function = counted_leg_function
        return counted

    def _patch(self, module, name, replacement) -> None:
        self._originals.append((module, name, getattr(module, name)))
        setattr(module, name, replacement)

    def _labelled(self, function, context):
        """function, with its route costings counted under context."""

        def labelled(*args, **kwargs):
            outer, self._context = self._context, context
            try:
                return function(*args, **kwargs)
            finally:
                self._context = outer

        return labelled

    def install(self) -> None:
        """Before the AdaptiveMutation is built: it binds the operators then."""
        drive, latest_start = individual._drive, individual._latest_start
        evaluation = fitness_module.route_evaluation
        positions = insertion._positions_worth_costing
        crossover, ga_fitness = ga.order_crossover, ga.fitness

        def counted_drive(*args):
            self.drives += 1
            return drive(*args)

        def counted_latest_start(problem, v, route, buffer_sec):
            before = self.drives
            result = latest_start(problem, v, route, buffer_sec)
            if self.drives > before:  # no drive at all when nobody has a report time
                self.search_steps.append(self.drives - before - 1)  # the first drive is at lo
                gap = result[0] - problem.vehicles[v].available_from
                self.search_gap_hours.append(gap / 3600)
            return result

        def counted_evaluation(problem, v, route, buffer_sec=None):
            key = (v, tuple(route))
            where = (self.generation, self._context)
            self.costings[where] += 1
            if key in self._seen:
                self.repeats[where] += 1
            if self._context == "mutated child" and key in self._iteration:
                self.mutated_from_operators += 1
            self._seen.add(key)
            if self._context in ("removal", "insertion"):
                self._iteration.add(key)
            return evaluation(problem, v, route, buffer_sec)

        def counted_positions(problem, route, v, i):
            chosen = positions(problem, route, v, i)
            self.positions.append(len(chosen))
            return chosen

        def counted_crossover(*args):
            self._crossovers += 1
            self.generation = (self._crossovers - 1) // ga.POPULATION_SIZE + 1
            self._fitness_calls = 0
            self._iteration = set()
            return crossover(*args)

        def labelled_fitness(problem, ind):
            # _iterate costs the crossover child first, then (after destroy
            # and repair) the mutated child.
            context = "crossover child" if self._fitness_calls == 0 else "mutated child"
            self._fitness_calls += 1
            if self.generation == 0:
                context = "initial population"
            return self._labelled(ga_fitness, context)(problem, ind)

        self._patch(individual, "_drive", counted_drive)
        self._patch(individual, "_latest_start", counted_latest_start)
        self._patch(fitness_module, "route_evaluation", counted_evaluation)
        self._patch(removal, "route_evaluation", counted_evaluation)
        self._patch(insertion, "_positions_worth_costing", counted_positions)
        self._patch(ga, "order_crossover", counted_crossover)
        self._patch(ga, "fitness", labelled_fitness)
        for name in ("worst_removal", "random_removal", "shaw_removal"):
            self._patch(mutation, name, self._labelled(getattr(mutation, name), "removal"))
        self._patch(
            mutation, "greedy_insertion", self._labelled(mutation.greedy_insertion, "insertion")
        )

    def remove(self) -> None:
        for module, name, original in reversed(self._originals):
            setattr(module, name, original)
        self._originals.clear()

    def summary(self, generations: int, timed_legs: bool) -> str:
        steps = collections.Counter(self.search_steps)
        lines = [
            provenance_line(),
            f"Counters, seed 1, {TIME_LIMIT_SEC:g} s with counting wrappers: "
            f"{generations} generations (the last may be partial), leg functions "
            f"{'on' if timed_legs else 'off'}.",
            "",
            f"- Travel calls: {self.travel_calls:,} ({self.travel_calls / generations:,.0f} "
            "per generation).",
            f"- Departure searches: {len(self.search_steps):,}; steps after the first drive: "
            f"mean {statistics.mean(self.search_steps):.2f}, histogram "
            + ", ".join(f"{k}: {steps[k]:,}" for k in sorted(steps))
            + ".",
            "- Steps by how far the start lands from available_from: "
            + "; ".join(self._steps_by_gap())
            + ".",
            "- Positions fully costed per _best_position call (insertion): mean "
            f"{statistics.mean(self.positions):.2f} over {len(self.positions):,} calls.",
            "",
            "| Generation | Route costings in | Count | Repeat a route costed earlier in the "
            "solve |",
            "|---|---|---|---|",
        ]
        contexts = (
            "outside the GA loop", "initial population", "crossover child", "removal",
            "insertion", "mutated child",
        )  # fmt: skip
        for generation in range(self.generation + 1):
            for context in contexts:
                count = self.costings[(generation, context)]
                if count:
                    repeats = self.repeats[(generation, context)]
                    lines.append(
                        f"| {generation} | {context} | {count:,} | {repeats / count * 100:.1f}% |"
                    )
        mutated = sum(n for (_, c), n in self.costings.items() if c == "mutated child")
        if mutated:
            share = self.mutated_from_operators / mutated * 100
            lines.append(
                f"\nOf the mutated child's routes, {share:.1f}% were costed by its own destroy "
                "and repair."
            )
        return "\n".join(lines)

    def _steps_by_gap(self) -> list[str]:
        buckets = collections.defaultdict(list)
        for steps, gap in zip(self.search_steps, self.search_gap_hours, strict=True):
            buckets[min(int(gap), 4)].append(steps)
        return [
            f"{'4+' if k == 4 else f'{k}-{k + 1}'} h: {len(v):,} searches, mean "
            f"{statistics.mean(v):.2f} steps"
            for k, v in sorted(buckets.items())
        ]


def counters(rf_travel: RfTravel, out: Path) -> str:
    counts = Counters()
    problem = rf_problem(rf_travel, counts.wrap_travel)
    counts.install()
    try:
        result = timed_solve(problem, 1)
    finally:
        counts.remove()
    text = counts.summary(result.generations, getattr(problem, "timed_legs", None) is not None)
    (out / "counters.md").write_text(text + "\n", encoding="utf-8")
    return text


def _plan(result) -> dict:
    return {
        "cost": repr(result.evaluation.cost),
        "routes": result.best.routes,
        "unassigned": result.best.unassigned,
    }


def fixed_generations(
    rf_travel: RfTravel, generations: int, label: str, record: bool, out: Path
) -> str:
    baseline_path = out / f"fixed_{generations}_baseline.json"
    baseline = {} if record else json.loads(baseline_path.read_text(encoding="utf-8"))
    rows = []
    probes = [probe()]  # probes[k] and probes[k + 1] bracket solve k
    for seed in SEEDS:
        seconds, per_probe, drift, windows = [], [], [], []
        for _ in range(REPEATS):
            problem = rf_problem(rf_travel)
            began = datetime.now().isoformat(timespec="seconds")
            started = time.perf_counter()
            result = frozen_solve(problem, seed, generations)
            seconds.append(time.perf_counter() - started)
            # Wall clock, to match against Windows power and session events.
            windows.append(f"{began}/{datetime.now().isoformat(timespec='seconds')}")
            probes.append(probe())
            per_probe.append(seconds[-1] / statistics.mean(probes[-2:]))
            drift.append(max(probes[-2:]) / min(probes[-2:]) - 1)
            if record:
                baseline[str(seed)] = _plan(result)
                baseline["provenance"] = PROVENANCE
            elif _plan(result) != baseline[str(seed)]:
                raise AssertionError(
                    f"seed {seed}: the plan differs from the baseline, so '{label}' is not exact"
                )
        rows.append({"label": label, "seed": seed, "generations": generations,
                     "seconds_min": round(min(seconds), 2),
                     "seconds_all": " ".join(f"{s:.2f}" for s in seconds),
                     # Each solve's seconds over the mean of its two probes.
                     "per_probe_min": round(min(per_probe), 3),
                     "probes": " ".join(f"{s:.2f}" for s in probes[-REPEATS - 1:]),
                     # The largest gap between the two probes around one solve.
                     "probe_drift_max": round(max(drift), 3),
                     "probe_flag": max(drift) > PROBE_DRIFT_FLAG,
                     "solve_windows": " ".join(windows),
                     "cost": float(baseline[str(seed)]["cost"]),
                     "head": PROVENANCE["head"][:7], "app_clean": PROVENANCE["app_clean"],
                     # Whether this tree's Problem built leg functions (#109 b).
                     "timed_legs": getattr(problem, "timed_legs", None) is not None,
                     "started": PROVENANCE["started"]})  # fmt: skip
        print(rows[-1], flush=True)
    if record:
        baseline_path.write_text(json.dumps(baseline, indent=1), encoding="utf-8")
    _append(out / f"fixed_{generations}.csv", rows)
    total = sum(r["seconds_min"] for r in rows)
    per_probe = sum(r["per_probe_min"] for r in rows)
    return (
        f"{label}: {total:.1f} s ({per_probe:.2f} probes) for {generations} generations"
        f" x {len(SEEDS)} seeds; probes {min(probes):.2f}-{max(probes):.2f} s"
    )


# A clean time-limited run (#109): its two probes within PROBE_DRIFT_FLAG of
# each other and both under PROBE_CEILING_SEC (on Best performance and cool,
# this machine's probe is 2.1-2.4 s; throttled, 2.5-3.6 s), and no Windows
# power or session event inside it. Each run follows a cool-down, against the
# throttling that sets in after minutes of continuous load.
PROBE_CEILING_SEC = 2.4
COOL_DOWN_SEC = 60.0
RETRIES = 2  # re-runs of a seed's block (or a single run) that was not clean
# The probes can miss partial throttling (block C: a clean run reached 21
# generations where the same setting reached 34 on every other seed), so a
# clean run whose generations are further than this from its setting's
# median on the other seeds is flagged as suspect.
GENERATIONS_SUSPECT = 0.15


def windows_events(began: datetime, ended: datetime) -> list[str]:
    """Windows power-source changes (Kernel-Power 105) and session changes
    (566: lock, unlock, input) between two times, as 'time id'."""
    query = (
        "Get-WinEvent -FilterHashtable @{LogName='System'; "
        "ProviderName='Microsoft-Windows-Kernel-Power'; Id=105,566; "
        f"StartTime=[datetime]'{began.isoformat()}'; EndTime=[datetime]'{ended.isoformat()}'}} "
        "-ErrorAction SilentlyContinue"
        " | ForEach-Object { $_.TimeCreated.ToString('s') + ' ' + $_.Id }"
    )
    run = subprocess.run(
        ["powershell", "-NoProfile", "-Command", query], capture_output=True, text=True
    )
    return [line.strip() for line in run.stdout.splitlines() if line.strip()]


def is_clean(row: dict) -> bool:
    """The clean-run rule above, from a run's recorded probes and events (so
    rows recorded under an earlier ceiling are judged by the current one)."""
    before, after = (float(x) for x in row["probes"].split())
    drift = max(before, after) / min(before, after) - 1
    return (
        drift <= PROBE_DRIFT_FLAG and max(before, after) <= PROBE_CEILING_SEC and not row["events"]
    )


def positions_name(positions) -> str:
    if positions is None:
        return "every"
    if positions == "current":
        return f"current ({positions_name(insertion.TIME_DEPENDENT_FULLY_COSTED_POSITIONS)})"
    return str(positions)


def time_limited_runs(
    rf_travel: RfTravel, travel: str, settings: list, seeds: list[int], label: str
) -> list[dict]:
    """One TIME_LIMIT_SEC solve per (seed, setting), the settings interleaved
    within each seed, each after a cool-down and between two probes. The
    setting "current" leaves TIME_DEPENDENT_FULLY_COSTED_POSITIONS as the
    code has it."""
    rows = []
    original = insertion.TIME_DEPENDENT_FULLY_COSTED_POSITIONS
    try:
        for seed in seeds:
            for positions in settings:
                insertion.TIME_DEPENDENT_FULLY_COSTED_POSITIONS = (
                    original if positions == "current" else positions
                )
                name = positions_name(positions)
                problem = rf_problem(rf_travel) if travel == "rf" else morning_wave_120()
                time.sleep(COOL_DOWN_SEC)
                before = probe()
                began = datetime.now()
                result = timed_solve(problem, seed)
                ended = datetime.now()
                after = probe()
                drift = max(before, after) / min(before, after) - 1
                events = windows_events(began, ended)
                e = result.evaluation
                rows.append({"label": label, "travel": travel, "seed": seed, "positions": name,
                             "generations": result.generations, "cost": repr(e.cost),
                             # A solve can stop before the time limit, when it
                             # stops improving; then its generations are fewer.
                             "stop": result.stop_reason.value,
                             "seconds": round((ended - began).total_seconds()),
                             "late_crew": e.late_crew, "vehicles_used": e.vehicles_used,
                             "unassigned": e.unassigned, "probes": f"{before:.2f} {after:.2f}",
                             "probe_drift": round(drift, 3), "events": "; ".join(events),
                             "window": f"{began.isoformat(timespec='seconds')}/"
                                       f"{ended.isoformat(timespec='seconds')}",
                             "head": PROVENANCE["head"][:7],
                             "app_clean": PROVENANCE["app_clean"], "app": PROVENANCE["app"],
                             "started": PROVENANCE["started"]})  # fmt: skip
                rows[-1]["clean"] = is_clean(rows[-1])
                print(rows[-1], flush=True)
    finally:
        insertion.TIME_DEPENDENT_FULLY_COSTED_POSITIONS = original
    return rows


def _with_retries(run, seeds: list[int]) -> list[dict]:
    """run(seeds) for every seed, then again (up to RETRIES times) for each
    seed whose block had a run that was not clean. Rows carry the attempt."""
    rows: list[dict] = []
    pending = list(seeds)
    for attempt in range(1, RETRIES + 2):
        block = run(pending)
        for row in block:
            row["attempt"] = attempt
        rows += block
        pending = [s for s in pending if not all(r["clean"] for r in block if r["seed"] == s)]
        if not pending:
            break
    return rows


def clean_blocks(rows: list[dict]) -> list[dict]:
    """Per seed, the rows of its last block whose runs were all clean; seeds
    with none are left out. Rows may come from a CSV (all strings)."""
    chosen = []
    for seed in dict.fromkeys(int(r["seed"]) for r in rows):
        mine = [r for r in rows if int(r["seed"]) == seed]
        for attempt in sorted({int(r["attempt"]) for r in mine}, reverse=True):
            block = [r for r in mine if int(r["attempt"]) == attempt]
            if all(is_clean(r) for r in block):
                chosen += block
                break
    return chosen


def suspects(rows: list[dict]) -> set[tuple[int, str]]:
    """(seed, setting) of runs whose generations are further than
    GENERATIONS_SUSPECT from the median of the same setting's other seeds."""
    flagged = set()
    for r in rows:
        others = [int(o["generations"]) for o in rows
                  if o["positions"] == r["positions"] and o["seed"] != r["seed"]]  # fmt: skip
        if others:
            median = statistics.median(others)
            if abs(int(r["generations"]) - median) > GENERATIONS_SUSPECT * median:
                flagged.add((int(r["seed"]), r["positions"]))
    return flagged


def paired_summary(rows: list[dict], flagged: set | None = None) -> list[str]:
    """Each pair of settings compared seed by seed. The same seed gives the
    same starting population, so the per-seed difference cancels most of
    the spread between seeds. A setting wins if it is cheaper on every
    seed, or its mean difference is larger than the spread (standard
    deviation) of the differences; otherwise the pair is ambiguous."""
    cost = {(int(r["seed"]), r["positions"]): float(r["cost"]) for r in rows}
    seeds = sorted({s for s, _ in cost})
    names = list(dict.fromkeys(r["positions"] for r in rows))
    flagged = flagged or set()
    lines = [
        "| Positions | Seed | Generations | Cost | Late crew | Vans |",
        "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| {r['positions']} | {r['seed']} | {r['generations']}"
        + (" (suspect)" if (int(r["seed"]), r["positions"]) in flagged else "")
        + f" | {float(r['cost']):,.0f} | {r['late_crew']} | {r['vehicles_used']} |"
        for r in sorted(rows, key=lambda r: (names.index(r["positions"]), int(r["seed"])))
    ]
    lines += ["", "| A vs B | A - B per seed | Mean | Spread | A cheaper on | Verdict |",
              "|---|---|---|---|---|---|"]  # fmt: skip
    for i, a in enumerate(names):
        for b in names[i + 1 :]:
            common = [s for s in seeds if (s, a) in cost and (s, b) in cost]
            diffs = [cost[(s, a)] - cost[(s, b)] for s in common]
            if len(diffs) < 2:
                continue
            mean, spread = statistics.mean(diffs), statistics.stdev(diffs)
            cheaper = sum(d < 0 for d in diffs)
            if cheaper == len(diffs) or (mean < 0 and -mean > spread):
                verdict = f"{a} wins"
            elif cheaper == 0 or (mean > 0 and mean > spread):
                verdict = f"{b} wins"
            else:
                verdict = "ambiguous"
            lines.append(
                f"| {a} vs {b} | "
                + ", ".join(f"{d:+,.0f}" for d in diffs)
                + f" | {mean:+,.0f} | {spread:,.0f} | {cheaper} of {len(diffs)} | {verdict} |"
            )
    return lines


def equal_time(rf_travel: RfTravel, settings: list, seeds: list[int], label: str, out: Path) -> str:
    rows = _with_retries(
        lambda pending: time_limited_runs(rf_travel, "rf", settings, pending, label), seeds
    )
    _append(out / "equal_time.csv", rows)
    # Every run under this label so far (earlier seeds too), so the verdicts
    # cover all seeds measured.
    with (out / "equal_time.csv").open(newline="", encoding="utf-8") as f:
        everything = [r for r in csv.DictReader(f) if r["label"] == label]
    chosen = clean_blocks(everything)
    measured = {int(r["seed"]) for r in everything}
    missing = sorted(measured - {int(r["seed"]) for r in chosen})
    flagged = suspects(chosen)
    lines = [
        provenance_line(),
        f"Equal time: {TIME_LIMIT_SEC:g} s per run, settings interleaved within each seed, "
        f"{COOL_DOWN_SEC:g} s cool-down before each; morning_wave_120 under RF travel.",
        f"Clean blocks only (probe drift <= {PROBE_DRIFT_FLAG:.0%}, probes <= "
        f"{PROBE_CEILING_SEC} s, no power or session event)"
        + (f"; no clean block for seed(s) {missing}." if missing else ".")
        + f" Suspect: generations more than {GENERATIONS_SUSPECT:.0%} from the setting's"
        " median on the other seeds.",
        "",
    ]
    return "\n".join(lines + paired_summary(chosen, flagged))


def equal_time_generations(out: Path) -> int:
    """The median generations every-position-costed reached in the clean
    equal-time blocks: the depth equal time actually delivers."""
    with (out / "equal_time.csv").open(newline="", encoding="utf-8") as f:
        chosen = clean_blocks([r for r in csv.DictReader(f) if r.get("attempt")])
    return round(
        statistics.median(int(r["generations"]) for r in chosen if r["positions"] == "every")
    )


def quality(
    rf_travel: RfTravel, settings: list, seeds: list[int], generations: int, label: str, out: Path
) -> str:
    """Cost after the same number of frozen-clock generations per setting:
    quality per generation, apart from speed. Not timed."""
    rows = []
    original = insertion.TIME_DEPENDENT_FULLY_COSTED_POSITIONS
    try:
        for seed in seeds:
            for positions in settings:
                insertion.TIME_DEPENDENT_FULLY_COSTED_POSITIONS = positions
                e = frozen_solve(rf_problem(rf_travel), seed, generations).evaluation
                rows.append({"label": label, "seed": seed, "positions": positions_name(positions),
                             "generations": generations, "cost": repr(e.cost),
                             "late_crew": e.late_crew, "vehicles_used": e.vehicles_used,
                             "unassigned": e.unassigned, "head": PROVENANCE["head"][:7],
                             "app_clean": PROVENANCE["app_clean"],
                             "started": PROVENANCE["started"]})  # fmt: skip
                print(rows[-1], flush=True)
    finally:
        insertion.TIME_DEPENDENT_FULLY_COSTED_POSITIONS = original
    _append(out / "quality.csv", rows)
    # Every run under this label at this depth so far (earlier seeds too).
    with (out / "quality.csv").open(newline="", encoding="utf-8") as f:
        everything = [r for r in csv.DictReader(f)
                      if r["label"] == label and int(r["generations"]) == generations]  # fmt: skip
    head = [provenance_line(), f"Cost after {generations} frozen-clock generations.", ""]
    return "\n".join(head + paired_summary(everything))


def generations_in_time(
    rf_travel: RfTravel, travel: str, seeds: list[int], label: str, out: Path
) -> str:
    """Generations one TIME_LIMIT_SEC solve reaches with the code as it is
    (before vs after #109), each run repeated if it was not clean."""
    rows = _with_retries(
        lambda pending: time_limited_runs(rf_travel, travel, ["current"], pending, label), seeds
    )
    _append(out / "generations_in_time.csv", rows)
    return (
        provenance_line()
        + "\n"
        + "\n".join(
            f"{r['travel']} seed {r['seed']} attempt {r['attempt']}: "
            f"{r['generations']} generations, cost {float(r['cost']):,.0f}, "
            f"{'clean' if r['clean'] else 'NOT clean'}"
            for r in rows
        )
    )


def _append(path: Path, rows: list[dict]) -> None:
    """Add rows to a results file, keeping earlier runs. Rewritten with every
    column when the new rows bring one the file lacks (earlier rows get it
    blank)."""
    earlier = []
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            earlier = list(csv.DictReader(f))
    fields = list(dict.fromkeys([k for row in earlier + rows for k in row]))
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(earlier + rows)


def _setting(text: str):
    """A --positions value: a number, none (every position costed), or
    current (as the code has it)."""
    if text == "none":
        return None
    if text == "current":
        return "current"
    return int(text)


def main() -> None:
    global TIME_LIMIT_SEC, COOL_DOWN_SEC
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--profile", action="store_true")
    mode.add_argument("--counters", action="store_true")
    mode.add_argument("--fixed-generations", type=int, metavar="N")
    mode.add_argument("--equal-time", action="store_true")
    mode.add_argument("--quality", metavar="N|auto")
    mode.add_argument("--generations-in-time", action="store_true")
    parser.add_argument("--record-baseline", action="store_true")
    parser.add_argument("--generations", type=int, help="--profile: frozen-clock generations")
    parser.add_argument("--label", default="run")
    parser.add_argument("--positions", nargs="+", default=["2", "3", "none"])
    parser.add_argument("--seeds", nargs="+", type=int, default=list(SEEDS))
    parser.add_argument("--travel", choices=["rf", "haversine"], default="rf")
    parser.add_argument("--out", type=Path, default=OUT)
    parser.add_argument("--time-limit", type=float, default=TIME_LIMIT_SEC, help="smoke tests only")
    parser.add_argument("--cool-down", type=float, default=COOL_DOWN_SEC, help="smoke tests only")
    args = parser.parse_args()
    TIME_LIMIT_SEC, COOL_DOWN_SEC = args.time_limit, args.cool_down
    settings = [_setting(p) for p in args.positions]

    args.out.mkdir(parents=True, exist_ok=True)
    rf_travel = RfTravel()
    if args.profile:
        text = profile(rf_travel, args.out, args.generations)
    elif args.counters:
        text = counters(rf_travel, args.out)
    elif args.fixed_generations:
        text = fixed_generations(
            rf_travel, args.fixed_generations, args.label, args.record_baseline, args.out
        )
        text = provenance_line() + "\n" + text
    elif args.equal_time:
        text = equal_time(rf_travel, settings, args.seeds, args.label, args.out)
    elif args.quality:
        n = equal_time_generations(args.out) if args.quality == "auto" else int(args.quality)
        text = quality(rf_travel, settings, args.seeds, n, args.label, args.out)
    else:
        text = generations_in_time(rf_travel, args.travel, args.seeds, args.label, args.out)
    print(text)


if __name__ == "__main__":
    main()
