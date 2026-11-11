**Zone matrix:** three anchors, 05:00 / 07:30 / 18:00 (#106).

On time under RF travel, % of all crew (unassigned count as not on time):

| Seed | RF plan | Haversine plan, fixed departures | Haversine plan, re-timed |
|---|---|---|---|
| 1 | 100.0 | 39.2 | 90.0 |
| 2 | 100.0 | 23.3 | 91.7 |
| 3 | 100.0 | 20.8 | 95.8 |
| 4 | 100.0 | 26.7 | 96.7 |
| 5 | 100.0 | 18.3 | 90.0 |
| 6 | 100.0 | 32.5 | 97.5 |
| 7 | 100.0 | 25.8 | 95.8 |
| 8 | 100.0 | 25.0 | 89.2 |
| 9 | 100.0 | 16.7 | 91.7 |
| 10 | 100.0 | 24.2 | 91.7 |
| Mean (range) | 100.0 (100.0 to 100.0) | 25.2 (16.7 to 39.2) | 93.0 (89.2 to 97.5) |

RF plan minus haversine plan, paired by seed (10 seeds), Wilcoxon signed-rank with Holm across the two (* below 0.05):

| Against | Mean difference, points | RF plan better / tied / worse | p (Holm) |
|---|---|---|---|
| Haversine plan, fixed departures | +74.8 | 10/0/0 | 0.0039 * |
| Haversine plan, re-timed | +7.0 | 10/0/0 | 0.0039 * |

Cross-evaluation: the haversine plan driven under RF travel.

| Seed | On time under haversine | Late under RF, fixed departures | Mean / max late (min) | Late under RF, re-timed | Max late re-timed (min) |
|---|---|---|---|---|---|
| 1 | 120 of 120 | 73 | 29.0 / 88.5 | 12 | 21.8 |
| 2 | 120 of 120 | 92 | 30.2 / 101.3 | 10 | 20.6 |
| 3 | 120 of 120 | 95 | 33.6 / 82.0 | 5 | 11.6 |
| 4 | 120 of 120 | 88 | 36.0 / 105.6 | 4 | 14.1 |
| 5 | 120 of 120 | 98 | 30.6 / 71.8 | 12 | 39.2 |
| 6 | 120 of 120 | 81 | 24.9 / 72.9 | 3 | 5.2 |
| 7 | 120 of 120 | 89 | 31.8 / 77.4 | 5 | 36.5 |
| 8 | 120 of 120 | 90 | 46.2 / 106.4 | 13 | 46.4 |
| 9 | 120 of 120 | 100 | 33.1 / 83.7 | 10 | 18.3 |
| 10 | 120 of 120 | 91 | 37.8 / 79.8 | 10 | 19.4 |

| Travel | Seed | Stop | Generations | Cost | Late crew | Lateness s | Vans | Travel s | Waiting s |
|---|---|---|---|---|---|---|---|---|---|
| haversine | 1 | no_improvement | 53 | 308,108 | 0 | 0 | 16 | 92199 | 154442 |
| haversine | 2 | no_improvement | 74 | 289,634 | 0 | 0 | 17 | 101146 | 125167 |
| haversine | 3 | no_improvement | 88 | 281,718 | 0 | 0 | 16 | 88163 | 135955 |
| haversine | 4 | no_improvement | 124 | 273,574 | 0 | 0 | 17 | 94016 | 118357 |
| haversine | 5 | time_limit | 132 | 270,941 | 0 | 0 | 15 | 89622 | 126204 |
| haversine | 6 | no_improvement | 63 | 296,536 | 0 | 0 | 16 | 92474 | 145930 |
| haversine | 7 | no_improvement | 67 | 290,329 | 0 | 0 | 16 | 90969 | 140704 |
| haversine | 8 | time_limit | 130 | 250,124 | 0 | 0 | 16 | 92682 | 98669 |
| haversine | 9 | no_improvement | 79 | 269,471 | 0 | 0 | 16 | 92773 | 119098 |
| haversine | 10 | no_improvement | 125 | 265,069 | 0 | 0 | 15 | 89084 | 121984 |
| rf | 1 | time_limit | 81 | 403,657 | 0 | 0 | 20 | 119336 | 212321 |
| rf | 2 | no_improvement | 38 | 431,170 | 0 | 0 | 20 | 121238 | 236924 |
| rf | 3 | time_limit | 78 | 403,362 | 0 | 0 | 20 | 122269 | 208131 |
| rf | 4 | no_improvement | 67 | 371,635 | 0 | 0 | 19 | 118159 | 185075 |
| rf | 5 | no_improvement | 71 | 367,316 | 0 | 0 | 20 | 121253 | 174063 |
| rf | 6 | no_improvement | 74 | 397,419 | 0 | 0 | 20 | 124132 | 199499 |
| rf | 7 | no_improvement | 68 | 401,291 | 0 | 0 | 20 | 120255 | 209037 |
| rf | 8 | time_limit | 81 | 390,390 | 0 | 0 | 18 | 108489 | 217100 |
| rf | 9 | time_limit | 83 | 371,164 | 0 | 0 | 20 | 119650 | 179514 |
| rf | 10 | time_limit | 83 | 394,864 | 0 | 0 | 20 | 124090 | 197270 |

Snap distances (121 places: pickups and the depot): median 2.28 km, max 10.31 km, 33.9% over 3 km.

## Notes

Run overnight on 10 to 11 November 2026, from `main` after #207 (RF fingerprint `f56265a7…`), on a quiet machine: 20 solves of 120 s, 32.5 min in all.

- **The headline:** under RF travel, the RF plan delivers all 120 crew on time in every seed. The haversine plan, driven at its own departure times, delivers 25.2% on time (16.7 to 39.2). That's a mean difference of 74.8 points, better in 10 of 10 seeds.
- **Re-timing alone doesn't fix the haversine plan:** with its departures moved earlier for RF travel, it still delivers only 93.0% on time (89.2 to 97.5). Up to 13 crew are late, by up to 46 min. So the gain comes from the routes, not only from leaving earlier. This is 7.0 points, better in 10 of 10.
- **Both p values are at the floor:** with 10 seeds, the smallest p a signed-rank test can give is 2/1024. Holm across two makes that 0.0039.
- **What being on time costs:** the RF plan uses 18 to 20 vans, against 15 to 17 for the haversine plan. Its cost under its own travel is about 41% higher (mean 393,227 against 279,550), because RF journey times are longer and the plan leaves more waiting. The haversine plan's lower cost is not real: it is only on time under travel times that are too short.
- **This is evaluated under the RF model,** the same model the RF plan was optimised against. So the RF plan's 100% shows that the solver meets every deadline the model gives it; it doesn't show how often crew would be on time on real roads. The RF's own error on the held-out logger is reported in #19 (MAPE 7.00%).
- **Against #104's interim 3 seeds:**
  - The RF solves ran 38 to 83 generations, against 6 to 7 then (#109's speed-up), and several stopped on no improvement. RF plan cost fell from about 480,000 to about 390,000.
  - Under fixed departures, more crew are late than then (73 to 100, against 66 to 81). This is most likely #106's corrected zone matrix, which removed the -14% morning bias on pickup-to-pickup legs.
  - Seeds 1 to 3's haversine plans are the same or close to #104's, as expected with the same seeds.
