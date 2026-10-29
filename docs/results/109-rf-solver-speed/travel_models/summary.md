**Zone matrix:** three anchors, 05:00 / 07:30 / 18:00 (#106).

Cross-evaluation: the haversine plan driven under RF travel.

| Seed | On time under haversine | Late under RF, fixed departures | Mean / max late (min) | Late under RF, re-timed | Max late re-timed (min) |
|---|---|---|---|---|---|
| 1 | 120 of 120 | 73 | 29.0 / 88.4 | 12 | 21.7 |
| 2 | 120 of 120 | 92 | 30.0 / 101.3 | 10 | 20.6 |
| 3 | 120 of 120 | 95 | 33.6 / 82.1 | 5 | 11.5 |

| Travel | Seed | Stop | Generations | Cost | Late crew | Lateness s | Vans | Travel s | Waiting s |
|---|---|---|---|---|---|---|---|---|---|
| haversine | 1 | no_improvement | 53 | 308,108 | 0 | 0 | 16 | 92199 | 154442 |
| haversine | 2 | no_improvement | 74 | 289,634 | 0 | 0 | 17 | 101146 | 125167 |
| haversine | 3 | no_improvement | 88 | 281,718 | 0 | 0 | 16 | 88163 | 135955 |
| rf | 1 | time_limit | 81 | 391,813 | 0 | 0 | 19 | 118501 | 204913 |
| rf | 2 | time_limit | 78 | 371,854 | 0 | 0 | 20 | 118371 | 180688 |
| rf | 3 | no_improvement | 76 | 384,261 | 0 | 0 | 20 | 117059 | 193693 |

Snap distances (121 places: pickups and the depot): median 2.28 km, max 10.31 km, 33.9% over 3 km.
