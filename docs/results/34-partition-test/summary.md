Partition test (#34): a driver's pickup events through a network that keeps failing. Run on 10 November 2026.

**No event was lost, and none was stored twice.** That holds across 21 seeded runs: seed 34, plus seeds 1 to 20.

## How it works

**Android half** (`android-client/.../outbox/PartitionTest.kt`, runs locally and in CI):
- **The real client side:** the app's outbox, Room, `ApiPickupEventUploader`, Retrofit, Moshi and OkHttp, including `apiCall`'s error mapping.
- **Only the socket is replaced,** by an OkHttp interceptor (`FlakyNetwork`) in front of a server double. The double follows the backend's rules for what the script can produce:
  - **Same key:** with the same fields it's `duplicate`; with different fields it's `idempotency_key_reused`.
  - **Second confirmation of a stop:** refused as `already_confirmed`.
- **The script, per seed:**
  - **Stops:** 100. At each one, maybe traffic delays, a vehicle issue or a no-show, then usually Crew on board. About 1 in 10 pickups get a second tap of Crew on board.
  - **Uploads:** the app tries every 1 to 6 events. About 1 in 10 tries the app restarts first (a new outbox over the same database), and about 1 in 10 two uploads start at once (a tap and a reconnect).
- **Faults:** each upload request draws one from the seed:

  | Fault | Chance | What happens |
  |---|---|---|
  | None | 50% | Reaches the server, answer comes back |
  | No connection | 20% | Never reaches the server |
  | Server error | 10% | A 503 in front of the server; nothing applied |
  | Response lost | 20% | The server applies it, then the connection drops before the answer arrives, so the app sends it again |

- **At the end,** the network heals and the app uploads until nothing is pending.

**Backend half** (`backend/tests/test_partition_replay_postgres.py`, CI's Postgres):
- **Replay:** seed 34's 57 deliveries that reached the server (`deliveries.json`) go through the real API into the real database, in the same order.
- **Checks:**
  - Every answer is the one the double gave.
  - Every recorded event is stored once, except the refused second taps.
  - No stop has two confirmations.
- **So the Android counts hold for the real server,** not only for the double.

**Loss** means an event the phone recorded that the server never stored. The second taps don't count: the server must refuse them.

## Results

| | Seed 34 (replayed on Postgres) | Seeds 1 to 20 |
|---|---|---|
| Events recorded on the phone | 237 | 4,601 (212 to 241 per seed) |
| Upload attempts | 70 | 1,362 |
| No connection / server error / response lost | 10 / 3 / 13 | 247 / 139 / 259 |
| App restarts / two uploads at once | 8 / 4 | 134 / 135 |
| Deliveries that reached the server | 57 | 976 |
| Events delivered more than once | 66 | 1,219 |
| Extra deliveries in all | 67 | 1,706 |
| Stored on the server | 227 | 4,397 |
| Refused as already_confirmed (second taps) | 10 | 204 |
| **Lost** | **0** | **0** |
| **Stored twice** | **0** | **0** |
| Stops confirmed twice | 0 | 0 |
| Pending on the phone at the end | 0 | 0 |

- **Duplicate deliveries happen often:** about a quarter of the events reached the server more than once, mostly after a lost response. The idempotency key turns each repeat into `duplicate`, which the app counts as synced, so nothing is stored twice.
- **The phone and the server agree:** every event the phone shows as sent is stored on the server, and each second tap shows on the phone as refused (`already_confirmed`).

Files: `deliveries.json` (seed 34's events and deliveries, for the replay), `report.json` (seed 34), `seeds.json` (seeds 1 to 20).

## Limits

- **The socket is replaced.** A real network's partial writes and timeouts aren't exercised, only their effects on the app: no answer, a 503, or an answer lost after the server applied the batch.
- **The double stands in for the server on Android;** the replay checks it against the real API for seed 34 only.
- **One driver on one phone.** Two phones uploading for the same stop are covered by the backend's concurrency tests (`test_pickup_events_postgres.py`), not here.
- **App restarts happen between uploads,** not in the middle of a database write.

Rerun from `android-client/`: `gradlew testDebugUnitTest --tests "com.kq.acdos.data.outbox.PartitionTest"`. It writes to `app/build/partition/`; copy the files here.
