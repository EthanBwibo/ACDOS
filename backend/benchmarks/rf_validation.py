"""Validate the Random Forest on real logged observations (#103).

The truth is travel_time_observations: Google's duration_in_traffic from
each zone to JKIA, logged hourly since 20 October 2026 (exported by
scripts/export_observations.sql). None of it was used to build Layers 1 to 3,
so all of it is held out. It is Google's estimate at the time of logging, not
a GPS trip.

Three predictions per observation, at its weekday and minute:
- rf: the Random Forest, interpolated between its hourly predictions exactly
  as the solver will use it (journey_time.HourlyGrid).
- static_baseline: one time per zone, whatever the hour (the zone's
  static_baseline_sec in trip_records.csv, the mean of its Layer 2 values).
  Chapter 3's comparison.
- l2_reference: Layer 2 interpolated directly (zone_matrix.Calibration). It
  generated the trips the RF learned from, so it is the reference the RF is
  expected to approximate.

Reported overall, per hour band and per zone: MAPE, MAE, mean signed error,
and the share of observations under-predicted by more than 10% (the risk
that matters for crew: a van that leaves too late). MAPEs and the RF minus
baseline MAPE difference get 95% confidence intervals from a cluster
bootstrap over logging runs: the 28 zones of one run share that hour's
traffic, so they are not independent observations; runs are resampled with
replacement.

Run from backend/:
    python -m benchmarks.rf_validation --cutoff 2026-10-26T13:00:00Z \
        --out ../docs/results/103-rf-validation
"""

import argparse
import csv
import random
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from app.ml import journey_time, zone_matrix

OBSERVATIONS_CSV = journey_time.DATA_DIR / "travel_time_observations.csv"
MODELS = ("rf", "static_baseline", "l2_reference")
# Hour bands, EAT, as [start, end) hours; night wraps past midnight.
BANDS = {"night": (21, 5), "morning": (5, 10), "midday": (10, 16), "evening": (16, 21)}
UNDER_PREDICTED = 0.10  # more than 10% too fast
BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 103


@dataclass(frozen=True)
class Observation:
    run_id: str
    logged_at_eat: str
    zone: str
    weekday: int  # Monday 0
    hour: float  # EAT, with minutes as a fraction
    actual_sec: float


def load_observations(path: Path = OBSERVATIONS_CSV) -> list[Observation]:
    with path.open(newline="", encoding="utf-8") as f:
        return [
            Observation(
                run_id=row["run_id"],
                logged_at_eat=row["logged_at_eat"],
                zone=row["zone"],
                weekday=journey_time.WEEKDAYS.index(row["day_of_week"].lower()),
                hour=int(row["hour_eat"]) + int(row["minute_eat"]) / 60,
                actual_sec=float(row["duration_in_traffic_sec"]),
            )
            for row in csv.DictReader(f)
        ]


def static_baselines(path: Path = journey_time.TRIP_RECORDS_CSV) -> dict[str, float]:
    with path.open(newline="", encoding="utf-8") as f:
        return {row["pickup_zone"]: float(row["static_baseline_sec"]) for row in csv.DictReader(f)}


def band(hour: float) -> str:
    for name, (start, end) in BANDS.items():
        inside = start <= hour < end if start < end else hour >= start or hour < end
        if inside:
            return name
    raise ValueError(hour)


def predict(
    observations: list[Observation],
    rf: journey_time.HourlyGrid,
    baseline: dict[str, float],
    l2: zone_matrix.Calibration,
) -> list[dict]:
    """One row per observation with the three predictions."""
    return [
        {
            "run_id": o.run_id,
            "logged_at_eat": o.logged_at_eat,
            "zone": o.zone,
            "band": band(o.hour),
            "actual_sec": o.actual_sec,
            "rf": round(rf.seconds(o.zone, o.weekday, o.hour), 1),
            "static_baseline": baseline[o.zone],
            "l2_reference": round(l2.seconds(o.zone, o.weekday, o.hour), 1),
        }
        for o in observations
    ]


def ape(row: dict, model: str) -> float:
    return abs(row[model] - row["actual_sec"]) / row["actual_sec"] * 100


def metrics(rows: list[dict], model: str) -> dict[str, float]:
    """MAPE, MAE, mean signed percentage error (below 0: too fast) and the
    share under-predicted by more than 10%, in %."""
    signed = [(r[model] - r["actual_sec"]) / r["actual_sec"] for r in rows]
    return {
        "mape": statistics.mean(ape(r, model) for r in rows),
        "mae_sec": statistics.mean(abs(r[model] - r["actual_sec"]) for r in rows),
        "mpe": statistics.mean(signed) * 100,
        "under_10_pct": sum(s < -UNDER_PREDICTED for s in signed) / len(rows) * 100,
    }


def cluster_bootstrap(
    rows: list[dict],
    statistic: Callable[[list[dict]], float],
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float]:
    """95% percentile interval of statistic, resampling whole runs (run_id)
    with replacement, each resample as many runs as there are."""
    by_run: dict[str, list[dict]] = {}
    for r in rows:
        by_run.setdefault(r["run_id"], []).append(r)
    runs = list(by_run)
    rng = random.Random(seed)
    values = sorted(
        statistic([r for run in rng.choices(runs, k=len(runs)) for r in by_run[run]])
        for _ in range(resamples)
    )
    return values[round(0.025 * (resamples - 1))], values[round(0.975 * (resamples - 1))]


def mape_of(model: str) -> Callable[[list[dict]], float]:
    return lambda rows: statistics.mean(ape(r, model) for r in rows)


def rf_minus_baseline(rows: list[dict]) -> float:
    return mape_of("rf")(rows) - mape_of("static_baseline")(rows)


def groups(rows: list[dict]) -> dict[str, list[dict]]:
    """All observations, then each hour band that has any."""
    found = {"all": rows}
    for name in BANDS:
        in_band = [r for r in rows if r["band"] == name]
        if in_band:
            found[name] = in_band
    return found


def summary(rows: list[dict], internal: dict, cutoff: str | None) -> str:
    runs = {r["run_id"] for r in rows}
    first, last = min(r["logged_at_eat"] for r in rows), max(r["logged_at_eat"] for r in rows)
    lines = [
        "**Interim.** The chapter numbers come from the re-run on the full set around 10 Nov.",
        "",
        f"{len(rows)} observations, {len(runs)} logging runs, {first} to {last} EAT"
        + (f", cutoff {cutoff}." if cutoff else "."),
        f"Bootstrap: {BOOTSTRAP_RESAMPLES} resamples of runs, seed {BOOTSTRAP_SEED}.",
        "",
        f"Internal check on trip_records (synthetic, {internal['test_rows']} held back): "
        f"MAPE {internal['mape']:.2f}%, MAE {internal['mae_sec']:.0f} s.",
        "",
        "| Hour band | n | Model | MAPE % | 95% CI | MAE s | Signed % | Under >10% % |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for name, subset in groups(rows).items():
        for model in MODELS:
            m = metrics(subset, model)
            low, high = cluster_bootstrap(subset, mape_of(model))
            lines.append(
                f"| {name} | {len(subset)} | {model} | {m['mape']:.2f} | {low:.2f} to {high:.2f} "
                f"| {m['mae_sec']:.0f} | {m['mpe']:+.2f} | {m['under_10_pct']:.1f} |"
            )
    lines += [
        "",
        "RF minus static baseline, MAPE points (below 0: the RF is better):",
        "",
        "| Hour band | Difference | 95% CI |",
        "|---|---|---|",
    ]
    for name, subset in groups(rows).items():
        low, high = cluster_bootstrap(subset, rf_minus_baseline)
        lines.append(f"| {name} | {rf_minus_baseline(subset):+.2f} | {low:+.2f} to {high:+.2f} |")
    lines += [
        "",
        "| Zone | n | RF MAPE % | Baseline MAPE % | L2 MAPE % | RF under >10% % |",
        "|---|---|---|---|---|---|",
    ]
    for zone in sorted({r["zone"] for r in rows}):
        subset = [r for r in rows if r["zone"] == zone]
        m = {model: metrics(subset, model) for model in MODELS}
        lines.append(
            f"| {zone} | {len(subset)} | {m['rf']['mape']:.2f} | "
            f"{m['static_baseline']['mape']:.2f} | {m['l2_reference']['mape']:.2f} | "
            f"{m['rf']['under_10_pct']:.1f} |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cutoff", help="the snapshot's cutoff, for the summary")
    parser.add_argument("--out", type=Path, default=Path("../docs/results/103-rf-validation"))
    args = parser.parse_args()

    model = journey_time.load_or_train()
    rows = predict(
        load_observations(),
        journey_time.predict_grid(model),
        static_baselines(),
        zone_matrix.load_calibration(),
    )
    text = summary(rows, journey_time.internal_check(), args.cutoff)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "validation.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.out / "summary.md").write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
