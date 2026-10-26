**Interim zone matrix:** pickup-to-pickup legs carry the known -14% morning bias (#106);
re-run after #106.

Cross-evaluation: the haversine plan driven under RF travel.

| Seed | On time under haversine | Late under RF, fixed departures | Mean / max late (min) | Late under RF, re-timed | Max late re-timed (min) |
|---|---|---|---|---|---|
| 1 | 120 of 120 | 66 | 24.3 / 68.3 | 11 | 19.8 |
| 2 | 120 of 120 | 81 | 28.0 / 74.5 | 0 | 0.0 |
| 3 | 120 of 120 | 70 | 37.1 / 84.0 | 11 | 18.1 |

| Travel | Seed | Stop | Generations | Cost | Late crew | Lateness s | Vans | Travel s | Waiting s |
|---|---|---|---|---|---|---|---|---|---|
| haversine | 1 | time_limit | 40 | 308,108 | 0 | 0 | 16 | 92199 | 154442 |
| haversine | 2 | time_limit | 41 | 289,927 | 0 | 0 | 17 | 98867 | 129860 |
| haversine | 3 | time_limit | 48 | 281,784 | 0 | 0 | 17 | 103074 | 114950 |
| rf | 1 | time_limit | 7 | 479,142 | 0 | 0 | 20 | 121922 | 268856 |
| rf | 2 | time_limit | 6 | 505,873 | 0 | 0 | 20 | 119742 | 302968 |
| rf | 3 | time_limit | 7 | 476,264 | 0 | 0 | 20 | 120724 | 281992 |

Snap distances (121 places: pickups and the depot): median 2.28 km, max 10.31 km, 33.9% over 3 km.
