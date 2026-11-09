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

The relative improvement over the baseline, (baseline MAPE - RF MAPE) /
baseline MAPE, is what NFR3 sets a floor on (at least 15%). It gets the same
kind of interval, overall, per hour band and per zone.

Run from backend/:
    python -m benchmarks.rf_validation --cutoff 2026-11-08T21:00:00Z \
        --out ../docs/results/21-rf-validation
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
NFR3_MIN_IMPROVEMENT = 15.0  # % of the static baseline's MAPE


@dataclass(frozen=True)
class Observation:
    run_id: str
    logged_at_eat: str
    zone: str
    weekday: int  # Monday 0
    hour: float  # EAT, with minutes as a fraction
    actual_sec: float


def load_observations(path: Path = OBSERVATIONS_CSV) -> list[Observation]:
    """Rows Google returned without a traffic time are left out: the free-flow
    duration_sec is a different quantity, so it cannot stand in for one."""
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
            if row["duration_in_traffic_sec"]
        ]


def count_without_traffic_time(path: Path = OBSERVATIONS_CSV) -> int:
    with path.open(newline="", encoding="utf-8") as f:
        return sum(not row["duration_in_traffic_sec"] for row in csv.DictReader(f))


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
    return lambda rows: statistics.fmean(ape(r, model) for r in rows)


def rf_minus_baseline(rows: list[dict]) -> float:
    return mape_of("rf")(rows) - mape_of("static_baseline")(rows)


def relative_improvement(rows: list[dict]) -> float:
    """How much of the static baseline's MAPE the RF removes, in %."""
    baseline = mape_of("static_baseline")(rows)
    return (baseline - mape_of("rf")(rows)) / baseline * 100


def rf_minus_l2(rows: list[dict]) -> float:
    return mape_of("rf")(rows) - mape_of("l2_reference")(rows)


def nfr3_verdict(point: float, low: float) -> str:
    """Met only if the whole interval clears the floor."""
    if low >= NFR3_MIN_IMPROVEMENT:
        return "yes"
    return "point estimate only" if point >= NFR3_MIN_IMPROVEMENT else "no"


def groups(rows: list[dict]) -> dict[str, list[dict]]:
    """All observations, then each hour band that has any."""
    found = {"all": rows}
    for name in BANDS:
        in_band = [r for r in rows if r["band"] == name]
        if in_band:
            found[name] = in_band
    return found


def notes(rows: list[dict], bands_met: int, zones_met: int) -> list[str]:
    """What the tables mean and what they cannot show, with their numbers."""
    m = {model: metrics(rows, model) for model in MODELS}
    gap_low, gap_high = cluster_bootstrap(rows, rf_minus_l2)
    bands = {name: subset for name, subset in groups(rows).items() if name != "all"}
    n_zones = len({r["zone"] for r in rows})
    more_often = [
        f"{name} ({metrics(subset, 'rf')['under_10_pct']:.1f}% against "
        f"{metrics(subset, 'static_baseline')['under_10_pct']:.1f}%)"
        for name, subset in bands.items()
        if metrics(subset, "rf")["under_10_pct"]
        > metrics(subset, "static_baseline")["under_10_pct"]
    ]
    return [
        "",
        f"NFR3 is met in {bands_met} of {len(bands)} hour bands and {zones_met} of "
        f"{n_zones} zones (whole interval at or above {NFR3_MIN_IMPROVEMENT:.0f}%).",
        "",
        "**MAPE is not the whole risk.** A prediction that is too fast means a van leaving "
        f"too late. Over all observations the RF is more than 10% too fast on "
        f"{m['rf']['under_10_pct']:.1f}%, the baseline on "
        f"{m['static_baseline']['under_10_pct']:.1f}%. The bands where the RF does this more "
        f"often than the baseline: {', '.join(more_often) or 'none'}. There the baseline is "
        "mostly safe because it is too slow, which is also why its MAPE is high.",
        "",
        "**What l2_reference is.** Layer 2, `data/temporal_calibration.csv`, read directly: "
        "3,332 Google Distance Matrix `best_guess` forecasts (28 zones x 7 weekdays x 17 "
        "hours), requested in one script run for the coming week, and interpolated linearly "
        "between the sampled hours round the week (`zone_matrix.Calibration`). It has no "
        "training step and no parameters. It is the function Layer 3 was generated from: "
        "`scripts/build_trip_records.py` takes this same interpolation (within each weekday's "
        "24 hours) and multiplies it by lognormal noise (CV 10%). The RF learns those noisy "
        "trips, so at best it recovers Layer 2. The static baseline is Layer 2 with time "
        "removed: each zone's mean over all its sampled values.",
        "",
        f"**How to read it.** The RF's MAPE is {m['rf']['mape']:.2f}% and Layer 2's is "
        f"{m['l2_reference']['mape']:.2f}%: the RF is {rf_minus_l2(rows):+.2f} points "
        f"(95% CI {gap_low:+.2f} to {gap_high:+.2f}). That gap is what the RF loses by "
        "learning Layer 2 from noisy samples. It is a ceiling for the RF on this data, not a "
        "competing method.",
        "",
        "**Why it is not the deployable model.** It could be loaded and queried: it is a "
        "lookup table, and on this test it is the more accurate. The reasons are about what it "
        "is, not whether it runs:",
        "",
        "- It cannot learn. It is one set of forecasts from one script run. It has no way to "
        "take in logged or real trips, and refreshing it means re-querying Google.",
        "- It disappears when real data arrives. Chapter 3.2.1's path replaces the synthetic "
        "Layer 3 with Kenya Airways trip records without touching the RF pipeline. Those "
        "records have no Layer 2 behind them, so there would be nothing to look up.",
        "- It is tied to its inputs: the 28 zones, to JKIA, by hour and weekday. The RF can "
        "take further features from real trips.",
        "- Its lead is partly the same-source advantage below.",
        "",
        "So the RF's case is not that it beats Layer 2 today. It is that it comes within about "
        "a point of it while being the component that can be retrained on real trips.",
        "",
        "**Limits of this validation.**",
        "",
        "- The truth is Google's `duration_in_traffic` at the time of logging, not a GPS trip. "
        "Layer 2 and so the RF also come from Google, so this shows agreement with Google's "
        "picture of Nairobi traffic, not accuracy against real vans. It favours Layer 2 most.",
        "- The interval resamples logging runs. Runs on the same day share weather and "
        "incidents, so the intervals may be somewhat too narrow.",
        "- Coverage is uneven at the start: 20 to 21 October have 9 runs in all, from the "
        "GitHub Actions logger. The logger ended at 07:07 EAT on 8 November, so that day is "
        "partial.",
    ]


def summary(rows: list[dict], internal: dict, cutoff: str | None, excluded: int = 0) -> str:
    runs = {r["run_id"] for r in rows}
    first, last = min(r["logged_at_eat"] for r in rows), max(r["logged_at_eat"] for r in rows)
    lines = [
        f"{len(rows)} observations, {len(runs)} logging runs, {first} to {last} EAT"
        + (f", cutoff {cutoff}." if cutoff else ".")
        + (f" {excluded} row(s) with no traffic time left out." if excluded else ""),
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
        f"NFR3: relative improvement over the static baseline, at least "
        f"{NFR3_MIN_IMPROVEMENT:.0f}%. Met means the whole 95% interval clears it.",
        "",
        "| Hour band | Relative improvement % | 95% CI | Met? |",
        "|---|---|---|---|",
    ]
    bands_met = zones_met = 0
    for name, subset in groups(rows).items():
        point = relative_improvement(subset)
        low, high = cluster_bootstrap(subset, relative_improvement)
        lines.append(
            f"| {name} | {point:.1f} | {low:.1f} to {high:.1f} | {nfr3_verdict(point, low)} |"
        )
        bands_met += name != "all" and nfr3_verdict(point, low) == "yes"
    lines += [
        "",
        "| Zone | n | RF MAPE % (95% CI) | Baseline MAPE % (95% CI) | L2 MAPE % "
        "| Relative improvement % (95% CI) | Met? | RF under >10% % |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for zone in sorted({r["zone"] for r in rows}):
        subset = [r for r in rows if r["zone"] == zone]
        m = {model: metrics(subset, model) for model in MODELS}
        rf_low, rf_high = cluster_bootstrap(subset, mape_of("rf"))
        base_low, base_high = cluster_bootstrap(subset, mape_of("static_baseline"))
        point = relative_improvement(subset)
        low, high = cluster_bootstrap(subset, relative_improvement)
        lines.append(
            f"| {zone} | {len(subset)} | {m['rf']['mape']:.2f} ({rf_low:.2f} to {rf_high:.2f}) | "
            f"{m['static_baseline']['mape']:.2f} ({base_low:.2f} to {base_high:.2f}) | "
            f"{m['l2_reference']['mape']:.2f} | {point:.1f} ({low:.1f} to {high:.1f}) | "
            f"{nfr3_verdict(point, low)} | {m['rf']['under_10_pct']:.1f} |"
        )
        zones_met += nfr3_verdict(point, low) == "yes"
    return "\n".join(lines + notes(rows, bands_met, zones_met))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--cutoff", help="the snapshot's cutoff, for the summary")
    parser.add_argument("--out", type=Path, default=Path("../docs/results/21-rf-validation"))
    args = parser.parse_args()

    model = journey_time.load_or_train()
    rows = predict(
        load_observations(),
        journey_time.predict_grid(model),
        static_baselines(),
        zone_matrix.load_calibration(),
    )
    text = summary(rows, journey_time.internal_check(), args.cutoff, count_without_traffic_time())
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "validation.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.out / "summary.md").write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
