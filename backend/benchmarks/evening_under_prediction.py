"""Why the Random Forest under-predicts in the evening, and what it costs (#202).

Reads the final validation's rows (docs/results/21-rf-validation/validation.csv,
from benchmarks/rf_validation.py) and Layer 3 (data/trip_records.csv).

Multipliers: a time divided by the zone's static_baseline_sec, the same
denominator for every source, so the multipliers of a zone compare directly.
- observed: what the logger saw.
- layer3: the mean over Layer 3's trips in that zone and hour, on every weekday
  and at any minute.
- layer3_at_logged_times: what Layer 3 expects at exactly the weekdays and
  minutes the logger ran: Layer 2 there, times the lognormal noise's mean. The
  plain layer3 mean can differ from the logger just because the two sampled
  different weekdays and minutes, which matters while traffic is building.

Buffer: the solver's latest departure aims to reach JKIA REPORT_BUFFER_SEC
before the earliest report time on board. If the leg to JKIA takes longer than
the RF said, the buffer takes the shortfall, and only a shortfall beyond it
makes crew late. This looks at the direct zone-to-JKIA leg, assuming the plan
kept its whole buffer; a plan that spent some of it has less, hence the smaller
buffers in the table.

Run from backend/, after rf_validation (which rewrites summary.md):
    python -m benchmarks.evening_under_prediction
"""

import argparse
import csv
import math
import statistics
from collections import Counter
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import numpy as np

from app.ml import journey_time
from app.solver.weights import REPORT_BUFFER_SEC
from benchmarks import rf_validation as rv

RESULTS_DIR = Path("../docs/results/21-rf-validation")
EVENING_HOURS = range(*rv.BANDS["evening"])
# scripts/build_trip_records.py's noise: lognormal(0, 0.10), whose mean is
# exp(0.1^2 / 2).
LOGNORMAL_MEAN = math.exp(0.10**2 / 2)
BUFFERS_SEC = (REPORT_BUFFER_SEC, 600.0, 300.0)
INTERIM_LAST_DAY = "2026-10-26"  # the end of #103's interim snapshot
SECTION = "## Evening under-prediction (#202)"


@dataclass(frozen=True)
class Layer3Trip:
    zone: str
    hour: int
    multiplier: float


def load_rows(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        for column in ("actual_sec", "rf", "static_baseline", "l2_reference"):
            r[column] = float(r[column])
        r["date"], r["hour"] = r["logged_at_eat"][:10], int(r["logged_at_eat"][11:13])
    return rows


def load_layer3(path: Path = journey_time.TRIP_RECORDS_CSV) -> list[Layer3Trip]:
    with path.open(newline="", encoding="utf-8") as f:
        return [
            Layer3Trip(
                row["pickup_zone"],
                int(row["hour_of_day"]),
                float(row["actual_duration_sec"]) / float(row["static_baseline_sec"]),
            )
            for row in csv.DictReader(f)
        ]


def observed_multiplier(row: dict) -> float:
    return row["actual_sec"] / row["static_baseline"]


def layer3_expected_multiplier(row: dict) -> float:
    return row["l2_reference"] * LOGNORMAL_MEAN / row["static_baseline"]


def is_under_predicted(row: dict) -> bool:
    """More than 10% too fast, as rf_validation counts it."""
    return (row["rf"] - row["actual_sec"]) / row["actual_sec"] < -rv.UNDER_PREDICTED


def shortfall_sec(row: dict, model: str = "rf") -> float:
    """How much longer the leg took than predicted; below 0 if it took less."""
    return row["actual_sec"] - row[model]


def still_late(row: dict, buffer_sec: float = REPORT_BUFFER_SEC, model: str = "rf") -> bool:
    return shortfall_sec(row, model) > buffer_sec


def share(flags: list[bool]) -> float:
    return sum(flags) / len(flags) * 100 if flags else 0.0


def multiplier_gap(rows: list[dict]) -> float:
    """Observed against what Layer 3 expects at the same times, in % of it."""
    observed = statistics.fmean(observed_multiplier(r) for r in rows)
    expected = statistics.fmean(layer3_expected_multiplier(r) for r in rows)
    return (observed / expected - 1) * 100


def zone_hour_rows(rows: list[dict], layer3: list[Layer3Trip]) -> list[dict]:
    """One row per zone and evening hour."""
    table = []
    for zone in sorted({r["zone"] for r in rows}):
        for hour in EVENING_HOURS:
            logged = [r for r in rows if r["zone"] == zone and r["hour"] == hour]
            trips = [t.multiplier for t in layer3 if t.zone == zone and t.hour == hour]
            table.append(
                {
                    "zone": zone,
                    "hour": hour,
                    "n_logged": len(logged),
                    "n_layer3": len(trips),
                    "observed": round(statistics.fmean(map(observed_multiplier, logged)), 3),
                    "layer3": round(statistics.fmean(trips), 3),
                    "layer3_at_logged_times": round(
                        statistics.fmean(map(layer3_expected_multiplier, logged)), 3
                    ),
                    "observed_vs_layer3_pct": round(multiplier_gap(logged), 1),
                    "rf_under_10_pct": round(share([is_under_predicted(r) for r in logged]), 1),
                    "still_late_pct": round(share([still_late(r) for r in logged]), 1),
                }
            )
    return table


def _multiplier_cells(rows: list[dict]) -> str:
    low, high = rv.cluster_bootstrap(rows, multiplier_gap)
    observed = statistics.fmean(map(observed_multiplier, rows))
    expected = statistics.fmean(map(layer3_expected_multiplier, rows))
    return (
        f"{observed:.3f} | {expected:.3f} | {multiplier_gap(rows):+.1f} "
        f"({low:+.1f} to {high:+.1f}) | {share([is_under_predicted(r) for r in rows]):.1f}"
    )


def _shortfall_cells(rows: list[dict]) -> str:
    under = [r for r in rows if is_under_predicted(r)]
    gaps = [shortfall_sec(r) / 60 for r in under]
    median, p90 = np.percentile(gaps, [50, 90]) if gaps else (0.0, 0.0)
    late = sum(still_late(r) for r in under)
    return (
        f"{len(rows)} | {len(under)} | {median:.1f} | {p90:.1f} | {max(gaps, default=0.0):.1f} | "
        f"{late} | {share([still_late(r) for r in under]):.1f} | "
        f"{share([still_late(r) for r in rows]):.1f}"
    )


def section(rows: list[dict], layer3: list[Layer3Trip]) -> str:
    evening = [r for r in rows if r["band"] == "evening"]
    multiplier_header = (
        "Observed multiplier | Layer 3 at logged times | Observed vs Layer 3 % (95% CI) "
        "| RF under >10% %"
    )
    lines = [
        SECTION,
        "",
        f"{len(evening)} evening observations (16:00 to 21:00 EAT). A multiplier is a time "
        "divided by the zone's static baseline.",
        "",
        "**1. Layer 3's evening multipliers against the logger.** Above 0: the evening was "
        "slower than Layer 3 expects at those weekdays and minutes. The per-zone, per-hour "
        "table, with Layer 3's own trip means, is `evening_zone_hour.csv`.",
        "",
        f"| Hour | n | Layer 3 trips, all weekdays | {multiplier_header} |",
        "|---|---|---|---|---|---|---|",
    ]
    for hour in EVENING_HOURS:
        subset = [r for r in evening if r["hour"] == hour]
        trips = statistics.fmean(t.multiplier for t in layer3 if t.hour == hour)
        lines.append(f"| {hour}:00 | {len(subset)} | {trips:.3f} | {_multiplier_cells(subset)} |")
    trips = statistics.fmean(t.multiplier for t in layer3 if t.hour in EVENING_HOURS)
    lines.append(f"| all | {len(evening)} | {trips:.3f} | {_multiplier_cells(evening)} |")

    lines += ["", f"| Period | n | {multiplier_header} |", "|---|---|---|---|---|---|"]
    periods = {
        "20 to 26 Oct (interim)": [r for r in evening if r["date"] <= INTERIM_LAST_DAY],
        "27 Oct to 2 Nov": [r for r in evening if INTERIM_LAST_DAY < r["date"] <= "2026-11-02"],
        "3 to 7 Nov": [r for r in evening if r["date"] > "2026-11-02"],
    }
    for name, subset in periods.items():
        lines.append(f"| {name} | {len(subset)} | {_multiplier_cells(subset)} |")

    lines += ["", f"| Weekday | n | {multiplier_header} |", "|---|---|---|---|---|---|"]
    for weekday, name in enumerate(w.capitalize() for w in journey_time.WEEKDAYS):
        subset = [r for r in evening if _weekday(r) == weekday]
        lines.append(f"| {name} | {len(subset)} | {_multiplier_cells(subset)} |")

    by_zone = sorted(
        {r["zone"] for r in evening},
        key=lambda z: -share([is_under_predicted(r) for r in evening if r["zone"] == z]),
    )
    lines += [
        "",
        "The ten zones most often under-predicted in the evening:",
        "",
        f"| Zone | n | {multiplier_header} |",
        "|---|---|---|---|---|---|",
    ]
    for zone in by_zone[:10]:
        subset = [r for r in evening if r["zone"] == zone]
        lines.append(f"| {zone} | {len(subset)} | {_multiplier_cells(subset)} |")

    cells = zone_hour_rows(evening, layer3)
    over_10 = sum(c["observed_vs_layer3_pct"] > 10 for c in cells)
    lines += [
        "",
        f"The logger is more than 10% above Layer 3 in {over_10} of the {len(cells)} zone-hour "
        "cells. The ten largest gaps:",
        "",
        "| Zone | Hour | Observed | Layer 3 trips | Layer 3 at logged times | Observed vs Layer 3 "
        "% | RF under >10% % |",
        "|---|---|---|---|---|---|---|",
    ]
    for c in sorted(cells, key=lambda c: -c["observed_vs_layer3_pct"])[:10]:
        lines.append(
            f"| {c['zone']} | {c['hour']}:00 | {c['observed']:.3f} | {c['layer3']:.3f} | "
            f"{c['layer3_at_logged_times']:.3f} | {c['observed_vs_layer3_pct']:+.1f} | "
            f"{c['rf_under_10_pct']:.1f} |"
        )

    shortfall_header = (
        "n | Under >10% | Median short (min) | 90th pct (min) | Max (min) | Still late "
        "| % of under-predictions | % of all"
    )
    lines += [
        "",
        f"**2. Would the {REPORT_BUFFER_SEC / 60:.0f}-minute buffer have absorbed them?** "
        "Short: how much longer the leg took than the RF said. Still late: short by more "
        "than the buffer.",
        "",
        f"| Hour | {shortfall_header} |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for hour in EVENING_HOURS:
        subset = [r for r in evening if r["hour"] == hour]
        lines.append(f"| {hour}:00 | {_shortfall_cells(subset)} |")
    lines.append(f"| all evening | {_shortfall_cells(evening)} |")

    lines += ["", "The same for every band:", "", f"| Band | {shortfall_header} |"]
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for name, subset in rv.groups(rows).items():
        lines.append(f"| {name} | {_shortfall_cells(subset)} |")

    lines += [
        "",
        "If the plan had already spent part of the buffer (evening observations, RF against "
        "the static baseline):",
        "",
        "| Buffer left (min) | RF: % of all still late | Baseline: % of all still late |",
        "|---|---|---|",
    ]
    for buffer_sec in BUFFERS_SEC:
        rf_late = share([still_late(r, buffer_sec) for r in evening])
        base_late = share([still_late(r, buffer_sec, "static_baseline") for r in evening])
        lines.append(f"| {buffer_sec / 60:.0f} | {rf_late:.1f} | {base_late:.1f} |")
    return "\n".join(lines + _conclusions(evening, periods))


def _weekday(row: dict) -> int:
    return date.fromisoformat(row["date"]).weekday()


def _conclusions(evening: list[dict], periods: dict[str, list[dict]]) -> list[str]:
    """What the tables add up to, with their numbers."""
    under = [r for r in evening if is_under_predicted(r)]
    late = [r for r in under if still_late(r)]
    rf_share = share([is_under_predicted(r) for r in evening])
    l2_share = rv.metrics(evening, "l2_reference")["under_10_pct"]
    gaps = [f"{name}: {multiplier_gap(subset):+.1f}%" for name, subset in periods.items()]
    runs = Counter(r["logged_at_eat"][:16] for r in late)
    zones = Counter(r["zone"].split(",")[0] for r in late).most_common(2)
    minutes = f"{REPORT_BUFFER_SEC / 60:.0f}"
    return [
        "",
        "**What this shows.**",
        "",
        f"- **The RF inherits this from Layer 2.** Layer 2 itself is more than 10% too fast on "
        f"{l2_share:.1f}% of evening observations, against the RF's {rf_share:.1f}%. The RF "
        "learned what it was given; this is not a learning failure.",
        f"- **The evenings became slower than Layer 2 forecast after the first week** "
        f"({'; '.join(gaps)}). That is why the share rose from 14.4% in #103 to "
        f"{rf_share:.1f}%. (14.1% in the first row above: that period runs to the end of 26 "
        "October, and #103 stopped at 15:07 EAT.) Layer 2 is one set of forecasts, committed "
        "on 20 October. These data cannot say why the evenings slowed.",
        "- **It is a weekday peak problem.** It is concentrated from 17:00 to 19:59 on Monday "
        "to Friday, and is small at weekends.",
        f"- **The buffer absorbs nearly all of it.** {len(late)} of {len(under)} evening "
        f"under-predictions ({share([still_late(r) for r in under]):.1f}%) are short by more "
        f"than {minutes} minutes, which is "
        f"{share([still_late(r) for r in evening]):.1f}% of all evening observations.",
        f"- **Those {len(late)} are not one bad evening.** They fall in {len(runs)} of the "
        f"logging runs, at most {max(runs.values())} in one. {zones[0][1]} are {zones[0][0]} "
        f"and {zones[1][1]} are {zones[1][0]}: on these long legs a fixed {minutes} minutes "
        "is a smaller share of the trip.",
        "",
        "**Limits.** This is the direct zone-to-JKIA leg only, and the logger's time stands "
        "for the real trip (Google's estimate, not GPS). A van with several stops also carries "
        "any error in its pickup-to-pickup legs, which this does not test. It assumes the plan "
        "kept its whole buffer, hence the smaller buffers above; a crew member reporting later "
        "than the earliest on board has more slack than this.",
    ]


def with_section(summary: str, text: str) -> str:
    """summary with this section added, replacing any earlier copy of it."""
    return summary.split(f"\n{SECTION}")[0].rstrip("\n") + "\n\n" + text + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--results", type=Path, default=RESULTS_DIR)
    args = parser.parse_args()

    rows = load_rows(args.results / "validation.csv")
    layer3 = load_layer3()
    table = zone_hour_rows(rows, layer3)
    with (args.results / "evening_zone_hour.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(table[0]))
        writer.writeheader()
        writer.writerows(table)
    text = section(rows, layer3)
    path = args.results / "summary.md"
    path.write_text(with_section(path.read_text(encoding="utf-8"), text), encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
