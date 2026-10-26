"""Held-out check of the zone matrix model (#102): its legs at the morning-peak
query (Q 07:30) against the matrix Google gave for that time, which the model
never sees.

For contrast, two models that ignore the time of day: the off-peak matrix
alone and the evening-peak matrix alone. Off-diagonal pairs only (the
diagonal is one point to Google).

Run from backend/:
    python -m benchmarks.zone_matrix_check --out ../docs/results/102-zone-matrix
"""

import argparse
import csv
import statistics
from pathlib import Path

from app.ml import zone_matrix

MODELS = ("blend", "off_peak_only", "evening_peak_only")


def check(matrix: zone_matrix.ZoneMatrix, queries: dict[str, zone_matrix.Query]) -> list[dict]:
    """One row per off-diagonal pair: the held-out seconds, each model's
    prediction and c."""
    held_out = queries[zone_matrix.MORNING_PEAK]
    off = queries[zone_matrix.OFF_PEAK].seconds
    peak = queries[zone_matrix.EVENING_PEAK].seconds
    rows = []
    for (o, d), actual in sorted(held_out.seconds.items()):
        if o == d:
            continue
        rows.append(
            {
                "origin_zone": o,
                "dest_zone": d,
                "actual_sec": actual,
                "c": round(matrix.congestion(o, d, held_out.weekday, held_out.hour), 4),
                "blend": round(matrix.leg(o, d, held_out.weekday, held_out.hour), 1),
                "off_peak_only": off[(o, d)],
                "evening_peak_only": peak[(o, d)],
            }
        )
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


def summary(rows: list[dict]) -> str:
    cs = [r["c"] for r in rows]
    lines = [
        f"{len(rows)} off-diagonal pairs at the held-out morning peak.",
        "",
        "| Model | MAPE % | Median APE % | P90 APE % | MAE s | Mean signed error % |",
        "|---|---|---|---|---|---|",
    ]
    for model in MODELS:
        e = errors(rows, model)
        lines.append(
            f"| {model} | {e['mape']:.2f} | {e['median_ape']:.2f} | {e['p90_ape']:.2f} "
            f"| {e['mae_sec']:.0f} | {e['mpe']:+.2f} |"
        )
    lines += [
        "",
        f"c at 07:30: min {min(cs):.2f}, median {statistics.median(cs):.2f}, max {max(cs):.2f}",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", type=Path, default=Path("../docs/results/102-zone-matrix"))
    args = parser.parse_args()
    queries = zone_matrix.load_queries()
    rows = check(zone_matrix.load(), queries)
    args.out.mkdir(parents=True, exist_ok=True)
    with (args.out / "held_out.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    print(summary(rows))


if __name__ == "__main__":
    main()
