**Zone matrix:** three anchors, 05:00 / 07:30 / 18:00 (#106).

Cross-evaluation: the haversine plan driven under RF travel.

| Seed | On time under haversine | Late under RF, fixed departures | Mean / max late (min) | Late under RF, re-timed | Max late re-timed (min) |
|---|---|---|---|---|---|
| 1 | 120 of 120 | 73 | 29.0 / 88.4 | 12 | 21.7 |
| 2 | 120 of 120 | 85 | 35.4 / 76.4 | 0 | 0.0 |
| 3 | 120 of 120 | 81 | 38.1 / 94.1 | 11 | 20.6 |

| Travel | Seed | Stop | Generations | Cost | Late crew | Lateness s | Vans | Travel s | Waiting s |
|---|---|---|---|---|---|---|---|---|---|
| haversine | 1 | time_limit | 39 | 308,108 | 0 | 0 | 16 | 92199 | 154442 |
| haversine | 2 | time_limit | 35 | 289,927 | 0 | 0 | 17 | 98867 | 129860 |
| haversine | 3 | time_limit | 37 | 281,784 | 0 | 0 | 17 | 103074 | 114950 |
| rf | 1 | time_limit | 5 | 565,229 | 0 | 0 | 20 | 122796 | 315782 |
| rf | 2 | time_limit | 5 | 479,435 | 0 | 0 | 20 | 122946 | 272256 |
| rf | 3 | time_limit | 5 | 443,998 | 0 | 0 | 20 | 126027 | 244927 |

Snap distances (121 places: pickups and the depot): median 2.28 km, max 10.31 km, 33.9% over 3 km.
