"""Held-out check of the zone matrix model (#102, #106): its legs at a query
time it never sees, against the matrix Google gave for that time.

#105 held out the 07:30 query against the two-anchor model. #106 made 07:30 an
anchor and holds out new queries on the same day (held_out_0830, and
held_out_1230 for the piece between the morning and evening anchors).

Models compared at each held-out time:
- three_anchor: the model with the 07:30 anchor (#106);
- two_anchor: the off-peak and evening-peak anchors only (#105);
- off_peak_only, morning_peak_only, evening_peak_only: one queried matrix
  whatever the hour. morning_peak_only shows how much of a gain near 07:30
  is just the anchor being close in time.
Off-diagonal pairs only (the diagonal is one point to Google).

Run from backend/:
    python -m benchmarks.zone_matrix_check --out ../docs/results/106-zone-matrix-anchor
    python -m benchmarks.zone_matrix_check --held-out morning_peak --two-anchor-only \
        --out ../docs/results/102-zone-matrix                       (#105's check)
"""

import argparse
import csv
import statistics
from pathlib import Path

from app.ml import zone_matrix

ANCHOR_MODELS = {
    "off_peak_only": zone_matrix.OFF_PEAK,
    "morning_peak_only": zone_matrix.MORNING_PEAK,
    "evening_peak_only": zone_matrix.EVENING_PEAK,
}


def check(
    models: dict[str, zone_matrix.ZoneMatrix],
    queries: dict[str, zone_matrix.Query],
    held_out_period: str,
) -> list[dict]:
    """One row per off-diagonal pair: the held-out seconds, c, each model's
    prediction and each single anchor matrix."""
    held_out = queries[held_out_period]
    any_model = next(iter(models.values()))
    rows = []
    for (o, d), actual in sorted(held_out.seconds.items()):
        if o == d:
            continue
        row = {
            "held_out": held_out_period,
            "origin_zone": o,
            "dest_zone": d,
            "actual_sec": actual,
            "c": round(any_model.congestion(o, d, held_out.weekday, held_out.hour), 4),
        }
        for name, model in models.items():
            row[name] = round(model.leg(o, d, held_out.weekday, held_out.hour), 1)
        for name, period in ANCHOR_MODELS.items():
            if period in queries and period != held_out_period:
                row[name] = queries[period].seconds[(o, d)]
        rows.append(row)
    return rows


def errors(rows: list[dict], model: str) -> dict[str, float]:
    """MAPE, median and 90th-percentile absolute percentage error, MAE, and
    the mean signed percentage error (below 0: the model is too fast)."""
    pe = [(r[model] - r["actual_sec"]) / r["actual_sec"] * 100 for r in rows]
    ape = [abs(e) for e in pe]
    return {
        "mape": statistics.mean(ape),
        "mpe": statistics.mean(pe),
        "median_ape": statistics.median(ape),
        "p90_ape": statistics.quantiles(ape, n=10)[-1],
        "mae_sec": statistics.mean(abs(r[model] - r["actual_sec"]) for r in rows),
    }


def summary(rows: list[dict], matrix: zone_matrix.ZoneMatrix | None = None) -> str:
    lines = [
        "| Held out | Model | MAPE % | Median APE % | P90 APE % | MAE s | Mean signed error % |",
        "|---|---|---|---|---|---|---|",
    ]
    for period in dict.fromkeys(r["held_out"] for r in rows):
        subset = [r for r in rows if r["held_out"] == period]
        models = [k for k in subset[0] if k not in ("held_out", "origin_zone", "dest_zone",
                                                    "actual_sec", "c")]  # fmt: skip
        for model in models:
            e = errors(subset, model)
            lines.append(
                f"| {period} | {model} | {e['mape']:.2f} | {e['median_ape']:.2f} "
                f"| {e['p90_ape']:.2f} | {e['mae_sec']:.0f} | {e['mpe']:+.2f} |"
            )
    lines.append("")
    for period in dict.fromkeys(r["held_out"] for r in rows):
        cs = [r["c"] for r in rows if r["held_out"] == period]
        lines.append(
            f"c at {period}: min {min(cs):.2f}, median {statistics.median(cs):.2f}, "
            f"max {max(cs):.2f}"
        )
    if matrix is not None:
        c_m = [
            c
            for o in matrix.zones
            for d in matrix.zones
            if o != d and (c := matrix.morning_congestion(o, d)) is not None
        ]
        if c_m:
            lines.append(
                f"c_m (where the 07:30 anchor sits): min {min(c_m):.3f}, "
                f"median {statistics.median(c_m):.3f}, max {max(c_m):.3f}; "
                f"{len(matrix.fallback_pairs)} pairs keep the two-anchor line."
            )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--held-out", nargs="+", help="periods to check (default: every held_out_* query)"
    )
    parser.add_argument(
        "--two-anchor-only", action="store_true", help="#105's model alone (07:30 not an anchor)"
    )
    parser.add_argument("--out", type=Path, default=Path("../docs/results/106-zone-matrix-anchor"))
    args = parser.parse_args()

    queries = zone_matrix.load_queries()
    periods = args.held_out or sorted(p for p in queries if p.startswith("held_out_"))
    two_anchor = zone_matrix.load(morning_anchor=False)
    if args.two_anchor_only:
        models, three_anchor = {"two_anchor": two_anchor}, None
    else:
        three_anchor = zone_matrix.load()
        models = {"three_anchor": three_anchor, "two_anchor": two_anchor}
    rows = [row for period in periods for row in check(models, queries, period)]

    text = summary(rows, three_anchor)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "held_out.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (args.out / "summary.md").write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
