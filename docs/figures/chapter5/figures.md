# Chapter 5 figures

300 dpi PNGs, drawn by `make_figures.py` from the final results CSVs. Every figure uses Times New Roman and the same palette:
- **Dark navy** is ACDOS: the RF, GA-ALNS, the 300 s run.
- **Light grey with hatching** is what it is compared against.
- **Black** marks a reference or a target.

The figures stay readable in black-and-white print.

To redraw them, run from the repository root. Only `matplotlib` and `numpy` are needed, not the backend's requirements:

```
pip install matplotlib numpy
python docs/figures/chapter5/make_figures.py
```

| Figure | File | Caption | Source |
|---|---|---|---|
| 5.1 | `fig5_1_mape_by_hour_band.png` | RF and static-baseline MAPE against the logged journeys, by hour band, with Layer 2 as reference. 95% bootstrap intervals over logging runs. | `docs/results/21-rf-validation/validation.csv` |
| 5.2 | `fig5_2_improvement_by_zone.png` | RF's relative improvement in MAPE over the static baseline in each of the 28 zones, against the 15% NFR3 target. | `docs/results/21-rf-validation/validation.csv` |
| 5.3 | `fig5_3_evening_under_prediction.png` | Evening journeys, by hour: (a) the RF under-predicts by more than 10%; (b) the shortfall exceeds the 15-minute buffer. | `docs/results/21-rf-validation/validation.csv` (as in `evening_zone_hour.csv` and `summary.md`) |
| 5.4 | `fig5_4_plain_ga_extra_distance.png` | Plain GA's extra distance over GA-ALNS on 20 Solomon instances, mean of 10 seeds at 60 s. R101's plain GA is infeasible. | `docs/results/203-plain-ga/results.csv` |
| 5.5 | `fig5_5_on_time_under_rf.png` | Crew on time when RF travel times are the truth: the RF plan, and the straight-line plan at its own and at re-timed departures, over 10 seeds. | `docs/results/210-travel-models-10-seeds/results.csv`, `cross_evaluation.csv` |
| 5.6 | `fig5_6_solomon_60_vs_300.png` | GA-ALNS's gap to best-known at 60 s and 300 s on R101, R105, RC101 and RC105: (a) distance, (b) vehicles. Bars are means; dots are seeds. | `docs/results/203-plain-ga/results.csv` (60 s), `docs/results/211-solomon-300s/results.csv` (300 s), `backend/benchmarks/solomon_data/best_known.csv` |
| 5.7 | `fig5_7_partition_test.png` | Partition test, seeds 1 to 20: events recorded, upload attempts and failures, duplicate deliveries, events stored, and events lost or stored twice (none). | `docs/results/34-partition-test/seeds.json` |

## Notes for the text

- **5.1:** the intervals are the ones in `21-rf-validation/summary.md`. The script repeats `rf_validation.py`'s bootstrap: 1000 resamples of runs, seed 103.
- **5.2:** every zone's whole 95% interval clears 15%. The lowest is Kayole, at 35.9% (31.0 to 40.5).
- **5.3 (b)** is a share of all journeys in that hour, not only the under-predicted ones. 17:00 is the worst hour, at 3.2%.
- **5.4, R101:** plain GA's distance looks low because all 10 runs leave 2 to 7 pickups unassigned, so it isn't a fair comparison. The two morning-wave instances are left out, because their distance is straight-line km and isn't part of the crew fitness.
- **5.5:** all the plans are judged by the RF model, so the RF plan meets the model it was built with. Read it alongside #210's caveat.
- **5.6:** RC105's distance at 300 s is below best-known, but it uses 2.5 more vans than best-known. Solomon ranks vans first.
- **5.7:** "stored twice" is the events stored, minus what should have been stored (recorded, less refused second taps, less lost). It is zero for every seed.
