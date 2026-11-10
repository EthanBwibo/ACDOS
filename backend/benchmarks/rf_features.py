"""Choose the Random Forest's features by cross-validation, then measure the
change on the logger (#18, #19).

Two stages, kept apart so the logger is never used to choose anything:

1. On data/trip_records.csv only. A seeded 80/20 train/test split
   (journey_time.split_trips). 5-fold cross-validation on the 80% scores each
   feature set in journey_time.FEATURE_SETS; the lowest mean MAPE is chosen.
   The 20% is scored once per feature set, after the choice, as a check.
2. On the logger (data/travel_time_observations.csv), held out as in #200.
   The "before" model (#103's plain features) and the chosen one are both
   trained on all of trip_records, as the app trains them, and scored as
   benchmarks/rf_validation.py scores the RF: interpolated at the
   observation's weekday and minute, MAPE with 95% cluster-bootstrap
   intervals over logging runs, and NFR3's relative improvement.

Layer 2 is not recalibrated on logger data: the logger stays held out.

Run from backend/:
    python -m benchmarks.rf_features --out ../docs/results/19-rf-features-cv
"""

import argparse
import csv
import random
import statistics
from collections.abc import Callable
from pathlib import Path

from app.ml import journey_time as jt
from app.ml import zone_matrix
from benchmarks import rf_validation as rv
from benchmarks.plain_ga import with_notes

FOLDS = 5
FOLD_SEED = 19
BEFORE = "plain"


def fold_indices(n: int, k: int = FOLDS, seed: int = FOLD_SEED) -> list[list[int]]:
    """k disjoint folds covering range(n): a seeded shuffle dealt round-robin,
    so fold sizes differ by at most one."""
    order = list(range(n))
    random.Random(seed).shuffle(order)
    return [sorted(order[f::k]) for f in range(k)]


def score(model: jt.JourneyTimeModel, trips: list[jt.Trip]) -> dict[str, float]:
    """MAPE (%) and MAE (s) of the model's hourly prediction on these trips."""
    predicted = model.predict([(t.zone, t.weekday, t.hour) for t in trips])
    errors = [p - t.duration_sec for p, t in zip(predicted, trips, strict=True)]
    return {
        "mape": statistics.fmean(
            abs(e) / t.duration_sec * 100 for e, t in zip(errors, trips, strict=True)
        ),
        "mae_sec": statistics.fmean(abs(e) for e in errors),
    }


def cross_validate(
    trips: list[jt.Trip],
    features: jt.Features,
    hyperparameters: dict,
    places: dict | None,
    k: int = FOLDS,
    seed: int = FOLD_SEED,
) -> list[dict[str, float]]:
    """One score per fold: trained on the other k - 1 folds, scored on it."""
    scores = []
    for held_out in fold_indices(len(trips), k, seed):
        out = set(held_out)
        training = [t for i, t in enumerate(trips) if i not in out]
        model = jt.fit(training, hyperparameters, features=features, places=places)
        scores.append(score(model, [trips[i] for i in held_out]))
    return scores


def choose(cv: dict[str, list[dict[str, float]]]) -> str:
    """The feature set with the lowest mean CV MAPE; on a tie, the earlier one
    in FEATURE_SETS (plain first, so a tie keeps the simpler model)."""
    return min(cv, key=lambda name: statistics.fmean(f["mape"] for f in cv[name]))


def cv_rows(cv, test) -> list[dict]:
    plain = [f["mape"] for f in cv[BEFORE]]
    rows = []
    for name, folds in cv.items():
        mapes = [f["mape"] for f in folds]
        rows.append(
            {
                "features": name,
                "cv_mape": statistics.fmean(mapes),
                "cv_mape_sd": statistics.stdev(mapes),
                "cv_mae_sec": statistics.fmean(f["mae_sec"] for f in folds),
                "folds_better_than_plain": sum(m < p for m, p in zip(mapes, plain, strict=True)),
                "test_mape": test[name]["mape"],
                "test_mae_sec": test[name]["mae_sec"],
                **{f"fold_{k + 1}_mape": m for k, m in enumerate(mapes)},
            }
        )
    return rows


# --- Stage 2: the logger, before against after ---


def improvement(model: str) -> Callable[[list[dict]], float]:
    """rf_validation.relative_improvement for any model column."""

    def statistic(rows: list[dict]) -> float:
        baseline = rv.mape_of("static_baseline")(rows)
        return (baseline - rv.mape_of(model)(rows)) / baseline * 100

    return statistic


def rf_minus_l2(model: str) -> Callable[[list[dict]], float]:
    return lambda rows: rv.mape_of(model)(rows) - rv.mape_of("l2_reference")(rows)


def after_minus_before(rows: list[dict]) -> float:
    """MAPE points; below 0, the new features are better."""
    return rv.mape_of("rf_after")(rows) - rv.mape_of("rf")(rows)


def logger_rows(before: jt.JourneyTimeModel, after: jt.JourneyTimeModel) -> list[dict]:
    """rf_validation's rows (rf is the before model), plus rf_after."""
    observations = rv.load_observations()
    baseline, l2 = rv.static_baselines(), zone_matrix.load_calibration()
    rows = rv.predict(observations, jt.predict_grid(before), baseline, l2)
    after_grid = jt.predict_grid(after)
    for row, o in zip(rows, observations, strict=True):
        row["rf_after"] = round(after_grid.seconds(o.zone, o.weekday, o.hour), 1)
    return rows


def _ci(rows, statistic, digits=2, signed=False) -> str:
    low, high = rv.cluster_bootstrap(rows, statistic)
    sign = "+" if signed else ""
    return f"{statistic(rows):{sign}.{digits}f} ({low:{sign}.{digits}f} to {high:{sign}.{digits}f})"


def logger_tables(rows: list[dict]) -> tuple[list[str], dict[str, int]]:
    lines = [
        "| Hour band | n | RF before MAPE % (95% CI) | RF after MAPE % (95% CI) "
        "| After minus before, points (95% CI) | NFR3 improvement before % | "
        "NFR3 improvement after % (95% CI) | Met after? | Under >10% before | Under >10% after |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for name, subset in rv.groups(rows).items():
        point = improvement("rf_after")(subset)
        low, _ = rv.cluster_bootstrap(subset, improvement("rf_after"))
        lines.append(
            f"| {name} | {len(subset)} | {_ci(subset, rv.mape_of('rf'))} | "
            f"{_ci(subset, rv.mape_of('rf_after'))} | "
            f"{_ci(subset, after_minus_before, signed=True)} | "
            f"{improvement('rf')(subset):.1f} | {_ci(subset, improvement('rf_after'), 1)} | "
            f"{rv.nfr3_verdict(point, low)} | {rv.metrics(subset, 'rf')['under_10_pct']:.1f} | "
            f"{rv.metrics(subset, 'rf_after')['under_10_pct']:.1f} |"
        )
    lines += [
        "",
        "| Zone | n | RF before MAPE % | RF after MAPE % | After minus before (95% CI) "
        "| Met before? | Met after? |",
        "|---|---|---|---|---|---|---|",
    ]
    met = {"before": 0, "after": 0}
    for zone in sorted({r["zone"] for r in rows}):
        subset = [r for r in rows if r["zone"] == zone]
        verdicts = {}
        for when, model in (("before", "rf"), ("after", "rf_after")):
            point = improvement(model)(subset)
            low, _ = rv.cluster_bootstrap(subset, improvement(model))
            verdicts[when] = rv.nfr3_verdict(point, low)
            met[when] += verdicts[when] == "yes"
        lines.append(
            f"| {zone} | {len(subset)} | {rv.mape_of('rf')(subset):.2f} | "
            f"{rv.mape_of('rf_after')(subset):.2f} | "
            f"{_ci(subset, after_minus_before, signed=True)} | "
            f"{verdicts['before']} | {verdicts['after']} |"
        )
    return lines, met


def summary(cv_table: list[dict], chosen: str, rows: list[dict] | None) -> str:
    lines = [
        f"Stage 1, trip_records only: {FOLDS}-fold cross-validation (fold seed {FOLD_SEED}) "
        "on the 80% training split (split seed 42); the 20% test split is scored once per "
        "feature set, after the choice. Hyperparameters fixed: "
        f"{jt.HYPERPARAMETERS}.",
        "",
        "| Features | CV MAPE % | SD across folds | CV MAE s | Folds better than plain "
        "| Test MAPE % | Test MAE s |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in cv_table:
        lines.append(
            f"| {r['features']} | {r['cv_mape']:.3f} | {r['cv_mape_sd']:.3f} | "
            f"{r['cv_mae_sec']:.1f} | {r['folds_better_than_plain']} of {FOLDS} | "
            f"{r['test_mape']:.3f} | {r['test_mae_sec']:.1f} |"
        )
    in_app = next(n for n, f in jt.FEATURE_SETS.items() if f == jt.FEATURES)
    lines += [
        "",
        f"Chosen by lowest mean CV MAPE: **{chosen}**. The app uses: **{in_app}**"
        + ("." if in_app == chosen else " (does not match the choice)."),
    ]
    if rows is not None:
        table, met = logger_tables(rows)
        runs = {r["run_id"] for r in rows}
        lines += [
            "",
            f"Stage 2, the logger (held out): {len(rows)} observations, {len(runs)} runs. "
            f"Before: {BEFORE} features (#200's model). After: {chosen}. Both trained on all "
            f"of trip_records. Bootstrap: {rv.BOOTSTRAP_RESAMPLES} resamples of runs, seed "
            f"{rv.BOOTSTRAP_SEED}.",
            "",
            *table,
            "",
            f"Zones meeting NFR3 (whole 95% interval at least {rv.NFR3_MIN_IMPROVEMENT:.0f}%): "
            f"{met['before']} of {len({r['zone'] for r in rows})} before, "
            f"{met['after']} after.",
            "",
            "RF minus l2_reference (Layer 2 itself), MAPE points: before "
            f"{_ci(rows, rf_minus_l2('rf'), signed=True)}, after "
            f"{_ci(rows, rf_minus_l2('rf_after'), signed=True)}.",
        ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=Path("../docs/results/19-rf-features-cv"))
    args = parser.parse_args()

    hyperparameters = jt.HYPERPARAMETERS
    places = jt.load_places()
    training, test = jt.split_trips(jt.load_trips())
    cv, held_out = {}, {}
    for name, features in jt.FEATURE_SETS.items():
        cv[name] = cross_validate(training, features, hyperparameters, places)
        print(f"{name}: CV MAPE {statistics.fmean(f['mape'] for f in cv[name]):.3f}", flush=True)
    chosen = choose(cv)
    for name, features in jt.FEATURE_SETS.items():
        model = jt.fit(training, hyperparameters, features=features, places=places)
        held_out[name] = score(model, test)
    table = cv_rows(cv, held_out)

    rows = None
    if chosen != BEFORE:
        before = jt.train(features=jt.FEATURE_SETS[BEFORE])
        after = jt.train(features=jt.FEATURE_SETS[chosen])
        rows = logger_rows(before, after)

    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "cv.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    if rows is not None:
        with (args.out / "logger.csv").open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(rows[0]))
            writer.writeheader()
            writer.writerows(rows)
    text = summary(table, chosen, rows)
    path = args.out / "summary.md"
    old = path.read_text(encoding="utf-8") if path.exists() else ""
    path.write_text(with_notes(text, old) + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
