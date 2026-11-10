Stage 1, trip_records only: 5-fold cross-validation (fold seed 19) on the 80% training split (split seed 42); the 20% test split is scored once per feature set, after the choice. Hyperparameters fixed: {'n_estimators': 200, 'min_samples_leaf': 5, 'random_state': 42, 'n_jobs': 1}.

| Features | CV MAPE % | SD across folds | CV MAE s | Folds better than plain | Test MAPE % | Test MAE s |
|---|---|---|---|---|---|---|
| plain | 8.814 | 0.141 | 146.3 | 0 of 5 | 8.716 | 145.4 |
| cyclic | 8.817 | 0.143 | 146.7 | 3 of 5 | 8.710 | 146.0 |
| spatial | 8.778 | 0.122 | 145.6 | 4 of 5 | 8.753 | 146.0 |
| cyclic_spatial | 8.763 | 0.107 | 145.6 | 5 of 5 | 8.743 | 146.5 |

Chosen by lowest mean CV MAPE: **cyclic_spatial**. The app uses: **cyclic_spatial**.

Stage 2, the logger (held out): 12403 observations, 443 runs. Before: plain features (#200's model). After: cyclic_spatial. Both trained on all of trip_records. Bootstrap: 1000 resamples of runs, seed 103.

| Hour band | n | RF before MAPE % (95% CI) | RF after MAPE % (95% CI) | After minus before, points (95% CI) | NFR3 improvement before % | NFR3 improvement after % (95% CI) | Met after? | Under >10% before | Under >10% after |
|---|---|---|---|---|---|---|---|---|---|
| all | 12403 | 7.01 (6.71 to 7.35) | 7.00 (6.71 to 7.34) | -0.01 (-0.05 to +0.03) | 58.2 | 58.3 (55.7 to 60.5) | yes | 9.5 | 9.7 |
| night | 4340 | 7.26 (6.95 to 7.58) | 7.20 (6.91 to 7.53) | -0.06 (-0.14 to +0.02) | 65.4 | 65.6 (62.7 to 68.1) | yes | 1.7 | 1.7 |
| morning | 2492 | 6.18 (5.79 to 6.65) | 6.21 (5.82 to 6.67) | +0.03 (-0.02 to +0.07) | 61.7 | 61.6 (56.6 to 65.6) | yes | 9.6 | 9.5 |
| midday | 3024 | 5.62 (5.33 to 5.90) | 5.70 (5.44 to 6.00) | +0.08 (+0.02 to +0.16) | 30.6 | 29.5 (25.0 to 34.1) | yes | 7.1 | 7.9 |
| evening | 2547 | 9.04 (8.07 to 10.39) | 8.97 (7.97 to 10.33) | -0.07 (-0.15 to +0.01) | 56.0 | 56.4 (49.6 to 61.6) | yes | 25.6 | 25.6 |

| Zone | n | RF before MAPE % | RF after MAPE % | After minus before (95% CI) | Met before? | Met after? |
|---|---|---|---|---|---|---|
| Athi River, Machakos County | 443 | 6.52 | 6.52 | -0.00 (-0.12 to +0.12) | yes | yes |
| Buruburu, Nairobi | 443 | 6.23 | 6.24 | +0.01 (-0.16 to +0.20) | yes | yes |
| Dagoretti, Nairobi | 443 | 7.25 | 7.13 | -0.12 (-0.19 to -0.04) | yes | yes |
| Donholm, Nairobi | 443 | 6.51 | 6.63 | +0.13 (+0.03 to +0.23) | yes | yes |
| Embakasi, Nairobi | 443 | 7.16 | 7.13 | -0.03 (-0.18 to +0.11) | yes | yes |
| Imara Daima, Nairobi | 443 | 9.00 | 8.91 | -0.09 (-0.30 to +0.11) | yes | yes |
| Kahawa, Nairobi | 443 | 6.12 | 6.11 | -0.01 (-0.12 to +0.10) | yes | yes |
| Karen, Nairobi | 443 | 5.13 | 5.16 | +0.03 (-0.06 to +0.11) | yes | yes |
| Kasarani, Nairobi | 443 | 6.48 | 6.42 | -0.05 (-0.21 to +0.11) | yes | yes |
| Kawangware, Nairobi | 443 | 8.55 | 8.21 | -0.33 (-0.48 to -0.17) | yes | yes |
| Kayole, Nairobi | 443 | 5.08 | 5.15 | +0.07 (-0.05 to +0.19) | yes | yes |
| Kilimani, Nairobi | 443 | 7.33 | 7.36 | +0.02 (-0.11 to +0.16) | yes | yes |
| Kitengela, Kajiado County | 443 | 7.96 | 7.81 | -0.15 (-0.30 to +0.01) | yes | yes |
| Langata, Nairobi | 443 | 5.88 | 5.83 | -0.05 (-0.17 to +0.07) | yes | yes |
| Lavington, Nairobi | 443 | 8.91 | 8.94 | +0.04 (-0.15 to +0.22) | yes | yes |
| Mlolongo, Machakos County | 443 | 8.38 | 8.31 | -0.07 (-0.23 to +0.09) | yes | yes |
| Nairobi CBD, Nairobi | 443 | 9.79 | 9.89 | +0.10 (+0.01 to +0.20) | yes | yes |
| Ngara, Nairobi | 443 | 8.37 | 8.41 | +0.05 (-0.14 to +0.25) | yes | yes |
| Nyayo Estate, Nairobi | 443 | 3.91 | 4.19 | +0.29 (+0.17 to +0.42) | yes | yes |
| Ongata Rongai, Kajiado County | 442 | 6.15 | 6.21 | +0.06 (-0.04 to +0.16) | yes | yes |
| Roysambu, Nairobi | 443 | 7.21 | 6.86 | -0.35 (-0.48 to -0.23) | yes | yes |
| Ruiru, Kiambu County | 443 | 5.75 | 5.60 | -0.14 (-0.27 to -0.03) | yes | yes |
| Runda, Nairobi | 443 | 8.69 | 8.59 | -0.10 (-0.19 to -0.00) | yes | yes |
| South B, Nairobi | 443 | 6.70 | 6.61 | -0.08 (-0.25 to +0.07) | yes | yes |
| South C, Nairobi | 443 | 5.70 | 5.75 | +0.05 (-0.06 to +0.15) | yes | yes |
| Umoja, Nairobi | 443 | 4.50 | 4.37 | -0.13 (-0.29 to +0.02) | yes | yes |
| Upper Hill, Nairobi | 443 | 6.83 | 6.81 | -0.02 (-0.11 to +0.07) | yes | yes |
| Westlands, Nairobi | 443 | 10.13 | 10.79 | +0.67 (+0.48 to +0.88) | yes | yes |

Zones meeting NFR3 (whole 95% interval at least 15%): 28 of 28 before, 28 after.

RF minus l2_reference (Layer 2 itself), MAPE points: before +0.98 (+0.88 to +1.08), after +0.97 (+0.87 to +1.07).

## Notes

**The new features make no practical difference.** Cyclic time and the zone's position were chosen by cross-validation, as agreed in advance, and they are what the app now uses. They neither help nor hurt on the logger.

**Stage 1: cross-validation on trip_records (#19).**
- **cyclic_spatial has the lowest mean CV MAPE,** 8.763% against plain's 8.814%: 0.05 points better, on all 5 folds.
- **Most of that comes from spatial** (8.778%, better on 4 of 5 folds). **Cyclic alone adds nothing** (8.817%).
- **On the 20% test split it is 0.03 points worse** than plain (8.743% against 8.716%). That is within fold-to-fold spread (SD about 0.1). The test split was scored after the choice, as a check, and doesn't change it: choosing on it, or on the logger, would use held-out data to select the model.

**Stage 2: before and after on the logger (#18).**
- **Overall:** MAPE 7.01% before (#200's figure, reproduced exactly) and 7.00% after. The difference is −0.01 points (95% CI −0.05 to +0.03), so there's no evidence of a change.
- **NFR3 is still met everywhere:** the relative improvement is 58.3% overall (55.7 to 60.5), every hour band clears 15%, and 28 of 28 zones still do.
- **Bands:** night and evening are slightly better and morning unchanged, all within ±0.07 points with CIs crossing 0. Midday is slightly worse, +0.08 points (+0.02 to +0.16), and still meets NFR3 at 29.5% (25.0 to 34.1).
- **Zones shuffle a little and cancel out.** Westlands is worst, +0.67 points (+0.48 to +0.88), and Nyayo Estate +0.29. Roysambu (−0.35) and Kawangware (−0.33) gain the most.
- **Evening under-prediction is unchanged:** 25.6% of evening observations are still more than 10% too fast.

**Why the features can't help much.**
- **One-hot zone already identifies each of the 28 zones,** so a zone's position adds no information about that zone. It only lets the trees group nearby zones, which gives the small CV gain.
- **Trees can split plain hour at any threshold.** What cyclic time adds is the wrap at midnight and from Sunday to Monday, and traffic there is flat night traffic.
- **The ceiling is Layer 2, not the features.** The RF stays about 1 point behind Layer 2 itself (+0.98 before, +0.97 after). Its remaining error against the logger is Layer 2's, such as the slower evenings in #202. No feature can learn that from trip_records. The logger isn't used to recalibrate Layer 2: it stays held out.

**What changes for the app.**
- **New model fingerprint:** `f56265a7…` (`RF_FINGERPRINT` in `.github/workflows/image.yml`), so the API needs redeploying.
- **Predictions move slightly,** and the solver's plans move with them; per zone this is at most 0.7 MAPE points on the logger.

**Limits.**
- **Hyperparameters are fixed,** the same as #103's, not tuned.
- **Cross-validation is on synthetic trips,** so it chooses the features that fit Layer 3 best. The logger is the real test, and it shows no change.
- **Folds are random, not leave-zone-out.** A new zone is where position would matter most, but the 28 zones are fixed.

From `backend/`: `python -m benchmarks.rf_features` (about 5 minutes). A rebuild keeps this section.
