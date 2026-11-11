"""Chapter 5 figures, drawn from the final results CSVs in docs/results/.

Run from the repository root:  python docs/figures/chapter5/make_figures.py
It needs only matplotlib and numpy (not the backend's requirements), and writes
fig5_1 to fig5_7 as 300 dpi PNGs next to this file. figures.md lists them.

Style, the same for every figure so they read as one set:
- Times New Roman, to match the report body.
- One palette: dark navy for what ACDOS does (the RF, GA-ALNS, the longer run),
  light grey with hatching for what it is compared against, black lines and
  markers for references and targets. Navy and light grey are far apart in
  lightness and the hatching stays when printed, so every figure reads in
  black and white.
- Numbers come straight from the CSVs. The bootstrap intervals in figures 1
  and 2 repeat rf_validation.py's: 1000 resamples of logging runs, seed 103.
"""

from __future__ import annotations

import csv
import json
import random
from collections import defaultdict
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parents[3]
RESULTS = ROOT / "docs" / "results"
OUT = Path(__file__).resolve().parent

# Palette.
OURS = "#1d3557"  # dark navy: the RF, GA-ALNS, 300 s
OURS_2 = "#6c8ebf"  # mid blue: a second series of ours (figure 5's re-timed plan)
OTHER = "#d9d9d9"  # light grey, always hatched: the comparison
INK = "black"  # references, targets, outlines
HATCH = "///"

WIDTH = 6.3  # inches: A4 text width with 2.5 cm margins
DPI = 300

plt.rcParams.update(
    {
        "font.family": "serif",
        "font.serif": ["Times New Roman", "Times", "DejaVu Serif"],
        "mathtext.fontset": "stix",
        "font.size": 10,
        "axes.titlesize": 10,
        "axes.labelsize": 10,
        "legend.fontsize": 9,
        "xtick.labelsize": 9,
        "ytick.labelsize": 9,
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.edgecolor": INK,
        "hatch.linewidth": 0.6,
        "legend.frameon": False,
        "savefig.dpi": DPI,
        "savefig.bbox": "tight",
    }
)

BOOTSTRAP_RESAMPLES = 1000
BOOTSTRAP_SEED = 103
NFR3_TARGET = 15.0
BUFFER_SEC = 900.0  # the solver's report buffer, REPORT_BUFFER_SEC
BANDS = ("night", "morning", "midday", "evening", "all")
BAND_LABELS = {
    "night": "Night\n21:00–05:00",
    "morning": "Morning\n05:00–10:00",
    "midday": "Midday\n10:00–16:00",
    "evening": "Evening\n16:00–21:00",
    "all": "All day",
}
MODELS = ("rf", "static_baseline", "l2_reference")


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def save(fig, name: str) -> None:
    fig.savefig(OUT / name)
    plt.close(fig)
    print("wrote", name)


# Figures 1 to 3: RF validation against the logger (#21, #202).


def validation_rows() -> list[dict]:
    rows = read_csv(RESULTS / "21-rf-validation" / "validation.csv")
    for r in rows:
        r["actual_sec"] = float(r["actual_sec"])
        for m in MODELS:
            r[m] = float(r[m])
            r["ape_" + m] = abs(r[m] - r["actual_sec"]) / r["actual_sec"] * 100
        r["hour"] = int(r["logged_at_eat"][11:13])
    return rows


def mape(rows: list[dict], model: str) -> float:
    return sum(r["ape_" + model] for r in rows) / len(rows)


def relative_improvement(rows: list[dict]) -> float:
    base = mape(rows, "static_baseline")
    return (base - mape(rows, "rf")) / base * 100


def cluster_bootstrap(rows: list[dict], statistic) -> tuple[float, float]:
    """rf_validation.cluster_bootstrap: whole runs resampled with replacement."""
    by_run: dict[str, list[dict]] = {}
    for r in rows:
        by_run.setdefault(r["run_id"], []).append(r)
    runs = list(by_run)
    rng = random.Random(BOOTSTRAP_SEED)
    values = sorted(
        statistic([r for run in rng.choices(runs, k=len(runs)) for r in by_run[run]])
        for _ in range(BOOTSTRAP_RESAMPLES)
    )
    n = BOOTSTRAP_RESAMPLES - 1
    return values[round(0.025 * n)], values[round(0.975 * n)]


def subset(rows: list[dict], band: str) -> list[dict]:
    return rows if band == "all" else [r for r in rows if r["band"] == band]


def fig1_mape_by_band(rows: list[dict]) -> None:
    x = np.arange(len(BANDS))
    w = 0.36
    fig, ax = plt.subplots(figsize=(WIDTH, 3.3))
    for i, (model, label, face, hatch) in enumerate(
        [
            ("rf", "Random Forest", OURS, None),
            ("static_baseline", "Static baseline", OTHER, HATCH),
        ]
    ):
        points, lows, highs = [], [], []
        for band in BANDS:
            s = subset(rows, band)
            points.append(mape(s, model))
            low, high = cluster_bootstrap(s, lambda rs, m=model: mape(rs, m))
            lows.append(low)
            highs.append(high)
        points = np.array(points)
        err = np.array([points - lows, np.array(highs) - points])
        xs = x + (i - 0.5) * w
        ax.bar(
            xs,
            points,
            w,
            color=face,
            hatch=hatch,
            edgecolor=INK,
            linewidth=0.6,
            label=label,
        )
        ax.errorbar(
            xs, points, yerr=err, fmt="none", ecolor=INK, elinewidth=0.8, capsize=2.5
        )
        for xi, h, p in zip(xs, highs, points):
            ax.text(xi, h + 0.3, f"{p:.1f}", ha="center", va="bottom", fontsize=8)
        print(model, [f"{p:.2f}" for p in points])
    l2 = [mape(subset(rows, b), "l2_reference") for b in BANDS]
    ax.scatter(
        x - 0.5 * w,
        l2,
        marker="D",
        s=22,
        color="white",
        edgecolor=INK,
        linewidth=0.9,
        zorder=3,
        label="Layer 2 reference",
    )
    ax.set_xticks(x, [BAND_LABELS[b] for b in BANDS])
    ax.set_ylabel("MAPE against the logger (%)")
    ax.set_ylim(0, 25)
    ax.legend(
        loc="lower center",
        bbox_to_anchor=(0.5, 1.0),
        ncol=3,
        fontsize=8.5,
        handlelength=1.6,
        columnspacing=1.2,
    )
    save(fig, "fig5_1_mape_by_hour_band.png")


def short_zone(zone: str) -> str:
    return zone.split(",")[0]


def fig2_improvement_by_zone(rows: list[dict]) -> None:
    by_zone = defaultdict(list)
    for r in rows:
        by_zone[r["zone"]].append(r)
    stats = []
    for zone, rs in by_zone.items():
        low, high = cluster_bootstrap(rs, relative_improvement)
        stats.append((relative_improvement(rs), low, high, zone))
    stats.sort()
    y = np.arange(len(stats))
    points = np.array([s[0] for s in stats])
    lows = np.array([s[1] for s in stats])
    highs = np.array([s[2] for s in stats])
    fig, ax = plt.subplots(figsize=(WIDTH, 6.4))
    ax.barh(y, points, 0.62, color=OURS, edgecolor=INK, linewidth=0.5)
    ax.errorbar(
        points,
        y,
        xerr=[points - lows, highs - points],
        fmt="none",
        ecolor=INK,
        elinewidth=0.8,
        capsize=2,
    )
    ax.axvline(NFR3_TARGET, color=INK, linestyle="--", linewidth=1.1)
    ax.text(
        NFR3_TARGET + 0.8,
        len(stats) - 0.4,
        "NFR3 target: 15%",
        va="bottom",
        fontsize=9,
    )
    ax.set_yticks(y, [short_zone(s[3]) for s in stats])
    ax.set_ylim(-0.7, len(stats) + 0.4)
    ax.set_xlim(0, 80)
    ax.set_xlabel("Relative improvement in MAPE over the static baseline (%)")
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    print(
        "zones",
        len(stats),
        "min",
        f"{points.min():.1f}",
        "lowest CI",
        f"{lows.min():.1f}",
    )
    save(fig, "fig5_2_improvement_by_zone.png")


def fig3_evening(rows: list[dict]) -> None:
    hours = (16, 17, 18, 19, 20)
    under, late, ns = [], [], []
    for h in hours:
        rs = [r for r in rows if r["band"] == "evening" and r["hour"] == h]
        ns.append(len(rs))
        under.append(
            sum((r["rf"] - r["actual_sec"]) / r["actual_sec"] < -0.10 for r in rs)
            / len(rs)
            * 100
        )
        late.append(
            sum(r["actual_sec"] - r["rf"] > BUFFER_SEC for r in rs) / len(rs) * 100
        )
    print(
        "evening n",
        ns,
        "under",
        [f"{u:.1f}" for u in under],
        "late",
        [f"{v:.1f}" for v in late],
    )
    x = np.arange(len(hours))
    labels = [f"{h}:00" for h in hours]
    fig, (a, b) = plt.subplots(1, 2, figsize=(WIDTH, 2.9))
    a.bar(x, under, 0.6, color=OURS, edgecolor=INK, linewidth=0.6)
    b.bar(x, late, 0.6, color=OURS, edgecolor=INK, linewidth=0.6)
    for ax, values, ylabel, title, top in (
        (a, under, "% of journeys", "(a) RF more than 10% too fast", 45),
        (b, late, "% of journeys", "(b) Still late after the 15-min buffer", 4.5),
    ):
        for xi, v in zip(x, values):
            ax.text(
                xi, v + top * 0.015, f"{v:.1f}", ha="center", va="bottom", fontsize=8
            )
        ax.set_xticks(x, labels)
        ax.set_xlabel("Hour of departure (EAT)")
        ax.set_ylabel(ylabel)
        ax.set_title(title, loc="left")
        ax.set_ylim(0, top)
    fig.tight_layout(w_pad=2.5)
    save(fig, "fig5_3_evening_under_prediction.png")


# Figure 4: plain GA against GA-ALNS (#203).


def fig4_plain_ga() -> None:
    rows = read_csv(RESULTS / "203-plain-ga" / "results.csv")
    dist = defaultdict(lambda: defaultdict(list))
    infeasible = defaultdict(int)
    for r in rows:
        if not r["instance"].lstrip("RC").isdigit():
            continue  # morning_wave and smoke: straight-line km, not Solomon's distance
        dist[r["instance"]][r["method"]].append(float(r["distance"]))
        if r["checker_feasible"] != "True":
            infeasible[(r["instance"], r["method"])] += 1
    instances = sorted(dist, key=lambda i: (i.startswith("RC"), int(i.lstrip("RC"))))
    extra = [
        (np.mean(dist[i]["plain_ga"]) - np.mean(dist[i]["ga_alns"]))
        / np.mean(dist[i]["ga_alns"])
        * 100
        for i in instances
    ]
    print("infeasible", dict(infeasible))
    flagged = [i for i in instances if infeasible[(i, "plain_ga")]]
    x = np.arange(len(instances))
    fig, ax = plt.subplots(figsize=(WIDTH, 3.1))
    for xi, inst, e in zip(x, instances, extra):
        bad = inst in flagged
        ax.bar(
            xi,
            e,
            0.66,
            color="white" if bad else OURS,
            hatch=HATCH if bad else None,
            edgecolor=INK,
            linewidth=0.6,
        )
        ax.text(xi, e + 0.5, f"{e:.0f}", ha="center", va="bottom", fontsize=7.5)
    for inst in flagged:
        xi = instances.index(inst)
        n = infeasible[(inst, "plain_ga")]
        ax.annotate(
            f"Plain GA infeasible\n({n} of 10 runs leave\npickups unassigned)",
            xy=(xi, extra[xi] + 2.2),
            xytext=(xi - 0.3, 36),
            fontsize=8,
            va="center",
            arrowprops={"arrowstyle": "-", "color": INK, "linewidth": 0.7},
        )
    ax.axvline(11.5, ymax=0.8, color=INK, linewidth=0.5, linestyle=":")
    ax.set_xticks(x, instances, rotation=90)
    ax.set_ylabel("Plain GA's extra distance\nover GA-ALNS (%)")
    ax.set_ylim(0, 41)
    ax.legend(
        ncol=2,
        bbox_to_anchor=(1.0, 1.04),
        handles=[
            Patch(facecolor=OURS, edgecolor=INK, label="Both feasible"),
            Patch(
                facecolor="white",
                hatch=HATCH,
                edgecolor=INK,
                label="Plain GA infeasible",
            ),
        ],
        loc="upper right",
    )
    save(fig, "fig5_4_plain_ga_extra_distance.png")


# Figure 5: crew on time under RF travel (#210).


def fig5_on_time() -> None:
    plans = read_csv(RESULTS / "210-travel-models-10-seeds" / "results.csv")
    cross = read_csv(RESULTS / "210-travel-models-10-seeds" / "cross_evaluation.csv")
    rf_plan = {
        int(r["seed"]): int(r["on_time"])
        / (int(r["on_time"]) + int(r["late_crew"]) + int(r["unassigned"]))
        * 100
        for r in plans
        if r["travel"] == "rf"
    }
    fixed = {
        int(r["seed"]): int(r["on_time_fixed"]) / int(r["crew"]) * 100 for r in cross
    }
    retimed = {
        int(r["seed"]): int(r["on_time_retimed"]) / int(r["crew"]) * 100 for r in cross
    }
    seeds = sorted(fixed)
    series = [
        ("RF plan", [rf_plan[s] for s in seeds], OURS, None),
        (
            "Straight-line plan, re-timed departures",
            [retimed[s] for s in seeds],
            OURS_2,
            None,
        ),
        (
            "Straight-line plan, its own departures",
            [fixed[s] for s in seeds],
            OTHER,
            HATCH,
        ),
    ]
    x = np.arange(len(seeds) + 1)  # the last group is the mean
    w = 0.27
    fig, ax = plt.subplots(figsize=(WIDTH, 3.3))
    for i, (label, values, face, hatch) in enumerate(series):
        mean = float(np.mean(values))
        print(label, f"mean {mean:.1f}", f"range {min(values):.1f}-{max(values):.1f}")
        # The mean goes in the legend: labels over three narrow bars collide.
        ax.bar(
            x + (i - 1) * w,
            values + [mean],
            w,
            color=face,
            hatch=hatch,
            edgecolor=INK,
            linewidth=0.5,
            label=f"{label} (mean {mean:.0f}%)",
        )
    ax.axvline(len(seeds) - 0.5, color=INK, linewidth=0.5, linestyle=":")
    ax.set_xticks(x, [str(s) for s in seeds] + ["Mean"])
    ax.set_xlabel("Seed (120 crew, morning wave)")
    ax.set_ylabel("Crew on time under RF travel (%)")
    ax.set_ylim(0, 105)
    ax.set_yticks(range(0, 101, 20))
    ax.legend(
        loc="lower left",
        bbox_to_anchor=(0.0, 1.0),
        ncol=1,
        fontsize=8.5,
        handlelength=1.6,
        columnspacing=1.2,
    )
    save(fig, "fig5_5_on_time_under_rf.png")


# Figure 6: Solomon at 60 s and 300 s (#203, #211).


def fig6_solomon() -> None:
    instances = ("R101", "R105", "RC101", "RC105")
    best = {
        r["instance"]: (int(r["vehicles"]), float(r["distance"]))
        for r in read_csv(
            ROOT / "backend" / "benchmarks" / "solomon_data" / "best_known.csv"
        )
        if r["instance"] in instances
    }
    runs = {
        "60 s": [
            r
            for r in read_csv(RESULTS / "203-plain-ga" / "results.csv")
            if r["method"] == "ga_alns" and r["instance"] in instances
        ],
        "300 s": [
            r
            for r in read_csv(RESULTS / "211-solomon-300s" / "results.csv")
            if r["instance"] in instances
        ],
    }
    gaps = {k: {i: [] for i in instances} for k in runs}
    vans = {k: {i: [] for i in instances} for k in runs}
    for k, rs in runs.items():
        for r in rs:
            bv, bd = best[r["instance"]]
            gaps[k][r["instance"]].append((float(r["distance"]) - bd) / bd * 100)
            vans[k][r["instance"]].append(int(r["vehicles"]) - bv)
    x = np.arange(len(instances))
    w = 0.36
    style = {"60 s": (OTHER, HATCH, -0.5), "300 s": (OURS, None, 0.5)}
    fig, (a, b) = plt.subplots(1, 2, figsize=(WIDTH, 3.0))
    rng = np.random.default_rng(0)  # jitter only, so seed points don't overlap
    for ax, data, ylabel, title in (
        (a, gaps, "Distance above best-known (%)", "(a) Distance gap"),
        (b, vans, "Vehicles above best-known", "(b) Vehicle gap"),
    ):
        for k in runs:
            face, hatch, offset = style[k]
            means = [np.mean(data[k][i]) for i in instances]
            xs = x + offset * w
            ax.bar(
                xs,
                means,
                w,
                color=face,
                hatch=hatch,
                edgecolor=INK,
                linewidth=0.6,
                label=k,
            )
            for xi, inst in zip(xs, instances):
                pts = data[k][inst]
                ax.scatter(
                    xi + rng.uniform(-0.09, 0.09, len(pts)),
                    pts,
                    s=7,
                    color="white",
                    edgecolor=INK,
                    linewidth=0.6,
                    zorder=3,
                )
            print(title, k, [f"{m:+.1f}" for m in means])
        ax.axhline(0, color=INK, linewidth=0.8)
        ax.set_xticks(x, instances)
        ax.set_ylabel(ylabel)
        ax.set_title(title, loc="left")
    a.legend(loc="upper right", title="GA-ALNS run", title_fontsize=9)
    b.set_yticks(range(5))
    fig.tight_layout(w_pad=2.5)
    save(fig, "fig5_6_solomon_60_vs_300.png")


# Figure 7: the partition test (#34).


def fig7_partition() -> None:
    seeds = json.loads(
        (RESULTS / "34-partition-test" / "seeds.json").read_text(encoding="utf-8")
    )
    total = defaultdict(int)
    for s in seeds:
        failed = sum(v for k, v in s["upload_attempts"].items() if k != "NONE")
        total["recorded"] += s["recorded"]
        total["failed"] += failed
        total["attempts"] += sum(s["upload_attempts"].values())
        total["extra"] += s["extra_deliveries"]
        total["stored"] += s["stored"]
        total["refused"] += s["refused_on_phone"]
        total["lost"] += s["lost"]
        # Every recorded event except the refused second taps and any lost ones
        # should be stored once; anything above that was stored twice.
        total["twice"] += s["stored"] - (s["recorded"] - s["second_taps"] - s["lost"])
        total["confirmed_twice"] += s["stops_confirmed_twice"]
    print(dict(total))
    bars = [
        ("Events recorded on the phone", total["recorded"], OURS),
        ("Upload attempts", total["attempts"], OURS),
        (
            "Uploads that failed\n(no connection, server error, response lost)",
            total["failed"],
            OTHER,
        ),
        ("Duplicate deliveries\n(the same event sent again)", total["extra"], OTHER),
        ("Events stored on the server", total["stored"], OURS),
        ("Second taps refused (already confirmed)", total["refused"], OURS),
        ("Events lost", total["lost"], INK),
        ("Events stored twice", total["twice"], INK),
    ]
    y = np.arange(len(bars))[::-1]
    fig, ax = plt.subplots(figsize=(WIDTH, 3.4))
    for yi, (label, value, face) in zip(y, bars):
        ax.barh(
            yi,
            value,
            0.62,
            color=face,
            hatch=HATCH if face == OTHER else None,
            edgecolor=INK,
            linewidth=0.5,
        )
        text = f"{value:,}" if value else "0"
        ax.text(
            value + 60,
            yi,
            text,
            va="center",
            fontsize=9,
            fontweight="bold" if face == INK else "normal",
        )
    ax.set_yticks(y, [b[0] for b in bars])
    ax.set_xlim(0, 5400)
    ax.set_xlabel("Count, seeds 1 to 20 (100 stops each)")
    ax.spines["left"].set_visible(False)
    ax.tick_params(axis="y", length=0)
    save(fig, "fig5_7_partition_test.png")


def main() -> None:
    rows = validation_rows()
    fig1_mape_by_band(rows)
    fig2_improvement_by_zone(rows)
    fig3_evening(rows)
    fig4_plain_ga()
    fig5_on_time()
    fig6_solomon()
    fig7_partition()


if __name__ == "__main__":
    main()
