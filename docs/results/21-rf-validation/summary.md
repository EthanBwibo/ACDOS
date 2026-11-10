12403 observations, 443 logging runs, 2026-10-20T06:42:29 to 2026-11-08T07:07:01 EAT, cutoff 2026-11-08T21:00:00Z. 1 row(s) with no traffic time left out.
Bootstrap: 1000 resamples of runs, seed 103.

Internal check on trip_records (synthetic, 3000 held back): MAPE 8.72%, MAE 145 s.

| Hour band | n | Model | MAPE % | 95% CI | MAE s | Signed % | Under >10% % |
|---|---|---|---|---|---|---|---|
| all | 12403 | rf | 7.01 | 6.71 to 7.35 | 124 | +1.82 | 9.5 |
| all | 12403 | static_baseline | 16.78 | 15.97 to 17.59 | 280 | +6.79 | 17.1 |
| all | 12403 | l2_reference | 6.03 | 5.72 to 6.37 | 108 | +1.05 | 8.5 |
| night | 4340 | rf | 7.26 | 6.95 to 7.58 | 108 | +6.01 | 1.7 |
| night | 4340 | static_baseline | 20.95 | 19.91 to 22.01 | 288 | +20.10 | 1.4 |
| night | 4340 | l2_reference | 6.24 | 5.93 to 6.56 | 94 | +5.12 | 1.4 |
| morning | 2492 | rf | 6.18 | 5.79 to 6.65 | 101 | +0.90 | 9.6 |
| morning | 2492 | static_baseline | 16.15 | 14.58 to 17.74 | 232 | +13.15 | 5.8 |
| morning | 2492 | l2_reference | 4.92 | 4.50 to 5.38 | 82 | -0.35 | 8.4 |
| midday | 3024 | rf | 5.62 | 5.33 to 5.90 | 96 | +0.82 | 7.1 |
| midday | 3024 | static_baseline | 8.09 | 7.42 to 8.80 | 130 | +3.06 | 8.6 |
| midday | 3024 | l2_reference | 4.76 | 4.53 to 5.00 | 83 | +0.31 | 5.9 |
| evening | 2547 | rf | 9.04 | 8.07 to 10.39 | 204 | -3.24 | 25.6 |
| evening | 2547 | static_baseline | 20.58 | 18.49 to 22.74 | 493 | -17.70 | 65.0 |
| evening | 2547 | l2_reference | 8.26 | 7.24 to 9.70 | 185 | -3.64 | 23.7 |

RF minus static baseline, MAPE points (below 0: the RF is better):

| Hour band | Difference | 95% CI |
|---|---|---|
| all | -9.77 | -10.57 to -8.96 |
| night | -13.70 | -14.86 to -12.50 |
| morning | -9.97 | -11.51 to -8.37 |
| midday | -2.47 | -3.09 to -1.94 |
| evening | -11.53 | -13.57 to -9.29 |

NFR3: relative improvement over the static baseline, at least 15%. Met means the whole 95% interval clears it.

| Hour band | Relative improvement % | 95% CI | Met? |
|---|---|---|---|
| all | 58.2 | 55.6 to 60.4 | yes |
| night | 65.4 | 62.5 to 67.9 | yes |
| morning | 61.7 | 56.9 to 65.7 | yes |
| midday | 30.6 | 25.8 to 35.5 | yes |
| evening | 56.0 | 49.0 to 61.3 | yes |

| Zone | n | RF MAPE % (95% CI) | Baseline MAPE % (95% CI) | L2 MAPE % | Relative improvement % (95% CI) | Met? | RF under >10% % |
|---|---|---|---|---|---|---|---|
| Athi River, Machakos County | 443 | 6.52 (5.98 to 7.10) | 18.10 (17.04 to 19.29) | 5.88 | 64.0 (60.9 to 66.8) | yes | 14.7 |
| Buruburu, Nairobi | 443 | 6.23 (5.62 to 6.90) | 16.59 (15.69 to 17.44) | 4.86 | 62.4 (58.4 to 66.2) | yes | 9.9 |
| Dagoretti, Nairobi | 443 | 7.25 (6.75 to 7.78) | 14.62 (13.71 to 15.54) | 6.21 | 50.4 (47.9 to 53.0) | yes | 2.0 |
| Donholm, Nairobi | 443 | 6.51 (6.03 to 6.96) | 12.97 (12.11 to 13.83) | 5.71 | 49.8 (47.1 to 52.7) | yes | 8.1 |
| Embakasi, Nairobi | 443 | 7.16 (6.23 to 8.27) | 21.47 (20.34 to 22.63) | 6.46 | 66.7 (61.6 to 71.1) | yes | 13.5 |
| Imara Daima, Nairobi | 443 | 9.00 (8.08 to 9.97) | 27.20 (25.83 to 28.53) | 7.43 | 66.9 (63.1 to 70.5) | yes | 13.1 |
| Kahawa, Nairobi | 443 | 6.12 (5.64 to 6.53) | 9.76 (9.24 to 10.28) | 5.38 | 37.3 (34.0 to 41.1) | yes | 15.3 |
| Karen, Nairobi | 443 | 5.13 (4.77 to 5.58) | 11.61 (10.88 to 12.34) | 4.62 | 55.8 (51.7 to 59.5) | yes | 8.8 |
| Kasarani, Nairobi | 443 | 6.48 (5.96 to 7.05) | 16.30 (15.41 to 17.19) | 5.69 | 60.2 (56.4 to 63.3) | yes | 7.4 |
| Kawangware, Nairobi | 443 | 8.55 (8.07 to 9.06) | 16.00 (15.09 to 16.86) | 7.03 | 46.6 (43.0 to 49.9) | yes | 1.6 |
| Kayole, Nairobi | 443 | 5.08 (4.72 to 5.44) | 7.92 (7.43 to 8.42) | 3.90 | 35.9 (31.0 to 40.5) | yes | 2.3 |
| Kilimani, Nairobi | 443 | 7.33 (6.83 to 7.88) | 20.01 (18.93 to 21.08) | 6.41 | 63.3 (60.2 to 65.9) | yes | 10.4 |
| Kitengela, Kajiado County | 443 | 7.96 (7.29 to 8.61) | 20.08 (18.88 to 21.36) | 6.46 | 60.3 (57.1 to 63.5) | yes | 20.8 |
| Langata, Nairobi | 443 | 5.88 (5.38 to 6.42) | 12.90 (12.05 to 13.71) | 4.90 | 54.4 (50.2 to 57.9) | yes | 13.8 |
| Lavington, Nairobi | 443 | 8.91 (8.36 to 9.47) | 22.17 (21.03 to 23.26) | 8.37 | 59.8 (56.7 to 62.7) | yes | 6.8 |
| Mlolongo, Machakos County | 443 | 8.38 (7.72 to 9.15) | 22.78 (21.51 to 24.07) | 7.06 | 63.2 (59.8 to 66.3) | yes | 14.4 |
| Nairobi CBD, Nairobi | 443 | 9.79 (9.08 to 10.51) | 22.98 (21.81 to 24.01) | 8.92 | 57.4 (54.6 to 60.0) | yes | 25.5 |
| Ngara, Nairobi | 443 | 8.37 (7.83 to 8.92) | 21.89 (20.80 to 22.98) | 7.21 | 61.8 (59.0 to 64.3) | yes | 5.2 |
| Nyayo Estate, Nairobi | 443 | 3.91 (3.55 to 4.27) | 8.24 (7.65 to 8.86) | 3.50 | 52.6 (47.4 to 57.1) | yes | 4.1 |
| Ongata Rongai, Kajiado County | 442 | 6.15 (5.73 to 6.57) | 14.69 (13.78 to 15.53) | 5.25 | 58.1 (55.1 to 60.9) | yes | 9.0 |
| Roysambu, Nairobi | 443 | 7.21 (6.64 to 7.80) | 16.25 (15.33 to 17.18) | 5.44 | 55.6 (52.0 to 58.8) | yes | 12.9 |
| Ruiru, Kiambu County | 443 | 5.75 (5.37 to 6.15) | 11.92 (11.16 to 12.66) | 4.77 | 51.8 (48.2 to 55.3) | yes | 3.4 |
| Runda, Nairobi | 443 | 8.69 (8.26 to 9.15) | 18.26 (17.32 to 19.21) | 7.68 | 52.4 (49.1 to 55.4) | yes | 3.8 |
| South B, Nairobi | 443 | 6.70 (6.08 to 7.32) | 16.51 (15.50 to 17.56) | 5.76 | 59.4 (55.6 to 62.9) | yes | 12.4 |
| South C, Nairobi | 443 | 5.70 (5.22 to 6.28) | 19.04 (17.97 to 20.19) | 5.19 | 70.0 (66.6 to 73.0) | yes | 9.9 |
| Umoja, Nairobi | 443 | 4.50 (4.25 to 4.77) | 9.41 (8.77 to 10.04) | 3.81 | 52.2 (49.4 to 54.7) | yes | 1.1 |
| Upper Hill, Nairobi | 443 | 6.83 (6.30 to 7.42) | 17.76 (16.67 to 18.81) | 5.89 | 61.6 (58.2 to 64.7) | yes | 11.5 |
| Westlands, Nairobi | 443 | 10.13 (9.54 to 10.77) | 22.28 (21.29 to 23.31) | 9.00 | 54.6 (51.1 to 57.7) | yes | 4.1 |

NFR3 is met in 4 of 4 hour bands and 28 of 28 zones (whole interval at or above 15%).

**MAPE is not the whole risk.** A prediction that is too fast means a van leaving too late. Over all observations the RF is more than 10% too fast on 9.5%, the baseline on 17.1%. The bands where the RF does this more often than the baseline: night (1.7% against 1.4%), morning (9.6% against 5.8%). There the baseline is mostly safe because it is too slow, which is also why its MAPE is high.

**What l2_reference is.** Layer 2, `data/temporal_calibration.csv`, read directly: 3,332 Google Distance Matrix `best_guess` forecasts (28 zones x 7 weekdays x 17 hours), requested in one script run for the coming week, and interpolated linearly between the sampled hours round the week (`zone_matrix.Calibration`). It has no training step and no parameters. It is the function Layer 3 was generated from: `scripts/build_trip_records.py` takes this same interpolation (within each weekday's 24 hours) and multiplies it by lognormal noise (CV 10%). The RF learns those noisy trips, so at best it recovers Layer 2. The static baseline is Layer 2 with time removed: each zone's mean over all its sampled values.

**How to read it.** The RF's MAPE is 7.01% and Layer 2's is 6.03%: the RF is +0.98 points (95% CI +0.88 to +1.08). That gap is what the RF loses by learning Layer 2 from noisy samples. It is a ceiling for the RF on this data, not a competing method.

**Why it is not the deployable model.** It could be loaded and queried: it is a lookup table, and on this test it is the more accurate. The reasons are about what it is, not whether it runs:

- It cannot learn. It is one set of forecasts from one script run. It has no way to take in logged or real trips, and refreshing it means re-querying Google.
- It disappears when real data arrives. Chapter 3.2.1's path replaces the synthetic Layer 3 with Kenya Airways trip records without touching the RF pipeline. Those records have no Layer 2 behind them, so there would be nothing to look up.
- It is tied to its inputs: the 28 zones, to JKIA, by hour and weekday. The RF can take further features from real trips.
- Its lead is partly the same-source advantage below.

So the RF's case is not that it beats Layer 2 today. It is that it comes within about a point of it while being the component that can be retrained on real trips.

**Limits of this validation.**

- The truth is Google's `duration_in_traffic` at the time of logging, not a GPS trip. Layer 2 and so the RF also come from Google, so this shows agreement with Google's picture of Nairobi traffic, not accuracy against real vans. It favours Layer 2 most.
- The interval resamples logging runs. Runs on the same day share weather and incidents, so the intervals may be somewhat too narrow.
- Coverage is uneven at the start: 20 to 21 October have 9 runs in all, from the GitHub Actions logger. The logger ended at 07:07 EAT on 8 November, so that day is partial.

## Evening under-prediction (#202)

2547 evening observations (16:00 to 21:00 EAT). A multiplier is a time divided by the zone's static baseline.

**1. Layer 3's evening multipliers against the logger.** Above 0: the evening was slower than Layer 3 expects at those weekdays and minutes. The per-zone, per-hour table, with Layer 3's own trip means, is `evening_zone_hour.csv`.

| Hour | n | Layer 3 trips, all weekdays | Observed multiplier | Layer 3 at logged times | Observed vs Layer 3 % (95% CI) | RF under >10% % |
|---|---|---|---|---|---|---|
| 16:00 | 560 | 1.143 | 1.181 | 1.119 | +5.6 (+3.9 to +7.3) | 15.9 |
| 17:00 | 532 | 1.280 | 1.317 | 1.253 | +5.1 (-1.7 to +9.6) | 32.5 |
| 18:00 | 503 | 1.308 | 1.401 | 1.306 | +7.3 (+3.7 to +10.4) | 37.8 |
| 19:00 | 476 | 1.217 | 1.362 | 1.283 | +6.2 (+3.0 to +9.3) | 30.7 |
| 20:00 | 476 | 1.089 | 1.141 | 1.136 | +0.4 (-2.8 to +3.5) | 11.1 |
| all | 2547 | 1.197 | 1.279 | 1.218 | +5.1 (+3.3 to +6.6) | 25.6 |

| Period | n | Observed multiplier | Layer 3 at logged times | Observed vs Layer 3 % (95% CI) | RF under >10% % |
|---|---|---|---|---|---|
| 20 to 26 Oct (interim) | 868 | 1.189 | 1.192 | -0.2 (-4.2 to +2.8) | 14.1 |
| 27 Oct to 2 Nov | 979 | 1.304 | 1.217 | +7.2 (+5.1 to +8.9) | 29.7 |
| 3 to 7 Nov | 700 | 1.356 | 1.251 | +8.4 (+6.1 to +10.8) | 34.0 |

| Weekday | n | Observed multiplier | Layer 3 at logged times | Observed vs Layer 3 % (95% CI) | RF under >10% % |
|---|---|---|---|---|---|
| Monday | 280 | 1.368 | 1.313 | +4.2 (-0.5 to +8.9) | 28.9 |
| Tuesday | 308 | 1.360 | 1.310 | +3.8 (-6.1 to +11.5) | 32.8 |
| Wednesday | 308 | 1.398 | 1.282 | +9.1 (+5.6 to +12.0) | 34.7 |
| Thursday | 448 | 1.358 | 1.293 | +5.0 (+2.2 to +7.7) | 28.3 |
| Friday | 448 | 1.461 | 1.341 | +8.9 (+6.0 to +11.6) | 39.5 |
| Saturday | 447 | 1.051 | 1.030 | +2.1 (+0.5 to +3.6) | 9.8 |
| Sunday | 308 | 0.951 | 0.958 | -0.7 (-2.2 to +1.0) | 4.5 |

The ten zones most often under-predicted in the evening:

| Zone | n | Observed multiplier | Layer 3 at logged times | Observed vs Layer 3 % (95% CI) | RF under >10% % |
|---|---|---|---|---|---|
| Nairobi CBD, Nairobi | 91 | 1.496 | 1.282 | +16.7 (+13.6 to +19.6) | 64.8 |
| Kitengela, Kajiado County | 91 | 1.387 | 1.243 | +11.6 (+8.8 to +14.1) | 54.9 |
| Athi River, Machakos County | 91 | 1.344 | 1.222 | +9.9 (+7.4 to +12.3) | 45.1 |
| Mlolongo, Machakos County | 91 | 1.449 | 1.320 | +9.7 (+6.5 to +12.5) | 44.0 |
| Embakasi, Nairobi | 91 | 1.483 | 1.399 | +6.0 (+1.4 to +10.5) | 42.9 |
| Kahawa, Nairobi | 91 | 1.146 | 1.063 | +7.7 (+6.1 to +9.4) | 39.6 |
| Upper Hill, Nairobi | 91 | 1.329 | 1.261 | +5.4 (+3.1 to +7.4) | 35.2 |
| South B, Nairobi | 91 | 1.411 | 1.292 | +9.3 (+6.5 to +11.9) | 35.2 |
| Langata, Nairobi | 91 | 1.270 | 1.196 | +6.3 (+4.3 to +8.2) | 35.2 |
| Kilimani, Nairobi | 91 | 1.314 | 1.242 | +5.8 (+3.7 to +7.7) | 31.9 |

The logger is more than 10% above Layer 3 in 20 of the 140 zone-hour cells. The ten largest gaps:

| Zone | Hour | Observed | Layer 3 trips | Layer 3 at logged times | Observed vs Layer 3 % | RF under >10% % |
|---|---|---|---|---|---|---|
| Nairobi CBD, Nairobi | 16:00 | 1.456 | 1.248 | 1.174 | +24.0 | 60.0 |
| Nairobi CBD, Nairobi | 18:00 | 1.659 | 1.336 | 1.393 | +19.1 | 77.8 |
| Kitengela, Kajiado County | 17:00 | 1.512 | 1.324 | 1.305 | +15.9 | 63.2 |
| Nairobi CBD, Nairobi | 17:00 | 1.529 | 1.436 | 1.337 | +14.4 | 68.4 |
| Kitengela, Kajiado County | 18:00 | 1.496 | 1.311 | 1.311 | +14.2 | 66.7 |
| Athi River, Machakos County | 18:00 | 1.466 | 1.251 | 1.290 | +13.7 | 66.7 |
| Nairobi CBD, Nairobi | 19:00 | 1.518 | 1.314 | 1.336 | +13.6 | 64.7 |
| Mlolongo, Machakos County | 18:00 | 1.679 | 1.460 | 1.482 | +13.3 | 61.1 |
| Mlolongo, Machakos County | 17:00 | 1.576 | 1.558 | 1.394 | +13.1 | 57.9 |
| Embakasi, Nairobi | 16:00 | 1.146 | 1.053 | 1.014 | +13.0 | 35.0 |

**2. Would the 15-minute buffer have absorbed them?** Short: how much longer the leg took than the RF said. Still late: short by more than the buffer.

| Hour | n | Under >10% | Median short (min) | 90th pct (min) | Max (min) | Still late | % of under-predictions | % of all |
|---|---|---|---|---|---|---|---|---|
| 16:00 | 560 | 89 | 6.0 | 10.1 | 17.9 | 3 | 3.4 | 0.5 |
| 17:00 | 532 | 173 | 7.6 | 14.8 | 31.9 | 17 | 9.8 | 3.2 |
| 18:00 | 503 | 190 | 7.9 | 13.0 | 20.4 | 8 | 4.2 | 1.6 |
| 19:00 | 476 | 146 | 6.4 | 11.4 | 22.4 | 4 | 2.7 | 0.8 |
| 20:00 | 476 | 53 | 4.7 | 9.0 | 15.4 | 1 | 1.9 | 0.2 |
| all evening | 2547 | 651 | 6.9 | 12.7 | 31.9 | 33 | 5.1 | 1.3 |

The same for every band:

| Band | n | Under >10% | Median short (min) | 90th pct (min) | Max (min) | Still late | % of under-predictions | % of all |
|---|---|---|---|---|---|---|---|---|
| all | 12403 | 1178 | 5.9 | 11.4 | 39.6 | 41 | 3.5 | 0.3 |
| night | 4340 | 75 | 4.7 | 10.5 | 39.6 | 2 | 2.7 | 0.0 |
| morning | 2492 | 238 | 5.0 | 9.5 | 21.1 | 3 | 1.3 | 0.1 |
| midday | 3024 | 214 | 4.8 | 9.2 | 17.0 | 3 | 1.4 | 0.1 |
| evening | 2547 | 651 | 6.9 | 12.7 | 31.9 | 33 | 5.1 | 1.3 |

If the plan had already spent part of the buffer (evening observations, RF against the static baseline):

| Buffer left (min) | RF: % of all still late | Baseline: % of all still late |
|---|---|---|
| 15 | 1.3 | 20.1 |
| 10 | 5.4 | 34.3 |
| 5 | 19.9 | 51.5 |

**What this shows.**

- **The RF inherits this from Layer 2.** Layer 2 itself is more than 10% too fast on 23.7% of evening observations, against the RF's 25.6%. The RF learned what it was given; this is not a learning failure.
- **The evenings became slower than Layer 2 forecast after the first week** (20 to 26 Oct (interim): -0.2%; 27 Oct to 2 Nov: +7.2%; 3 to 7 Nov: +8.4%). That is why the share rose from 14.4% in #103 to 25.6%. (14.1% in the first row above: that period runs to the end of 26 October, and #103 stopped at 15:07 EAT.) Layer 2 is one set of forecasts, committed on 20 October. These data cannot say why the evenings slowed.
- **It is a weekday peak problem.** It is concentrated from 17:00 to 19:59 on Monday to Friday, and is small at weekends.
- **The buffer absorbs nearly all of it.** 33 of 651 evening under-predictions (5.1%) are short by more than 15 minutes, which is 1.3% of all evening observations.
- **Those 33 are not one bad evening.** They fall in 19 of the logging runs, at most 4 in one. 13 are Kitengela and 7 are Athi River: on these long legs a fixed 15 minutes is a smaller share of the trip.

**Limits.** This is the direct zone-to-JKIA leg only, and the logger's time stands for the real trip (Google's estimate, not GPS). A van with several stops also carries any error in its pickup-to-pickup legs, which this does not test. It assumes the plan kept its whole buffer, hence the smaller buffers above; a crew member reporting later than the earliest on board has more slack than this.
