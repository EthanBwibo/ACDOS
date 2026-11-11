# ACDOS technical specification

**Draft for #40.** This specification is compiled from the README, `docs/openapi.json` (the API contract) and `docs/schema.md` (Table 4.1). Where those files go into detail, this document points to them rather than copying them. If this document and those sources disagree, the sources win.

## 1. Purpose and scope

ACDOS dispatches vans that collect Kenya Airways flight crew across Nairobi and deliver them to JKIA before their rostered report time. It also re-plans after a flight delay, a standby activation or a vehicle breakdown.

**In scope:**
- planning and re-planning pickups;
- journey-time prediction;
- driver pickup recording that works offline;
- preset messaging between crew and the dispatcher.

**Out of scope:** crew rostering, KCAA rest rules, CBA rules, and ground handling staff. The roster is a fixed external input.

## 2. Architecture

```
Android app (dispatcher · driver · crew)
   │  HTTPS + JSON, Supabase access token (JWT)
   ▼
FastAPI backend (Azure App Service, one uvicorn process)
   ├── routers/         REST API (docs/openapi.json)
   ├── jobs/            solver process pool (SOLVER_POOL_SIZE, default 2)
   │     └── solver/    GA-ALNS          ── uses ──▶ ml/ Random Forest journey times
   ▼
Supabase: Postgres + PostGIS, Auth, RLS
   └── Edge Function log-travel-times (validation logger, finished 8 Nov 2026)
```

| Component | Technology | Where |
|---|---|---|
| Android client | Kotlin, Views, coroutines, Room, Retrofit + Moshi, supabase-kt; minSdk 26 | `android-client/` |
| Backend API | Python, FastAPI, Pydantic models for every body, asyncpg | `backend/app/` |
| Solver | GA-ALNS in pure Python, run in separate processes | `backend/app/solver/`, design in `docs/solver_design.md` |
| Journey-time model | scikit-learn Random Forest, trained at image build | `backend/app/ml/` |
| Database | Supabase Postgres with PostGIS; schema only through numbered migrations | `backend/migrations/`, `docs/schema.md` |
| Auth | Supabase Auth (email and password); role in `profiles.role` | |
| Hosting | Azure App Service (Linux B1, Spain Central), image from GHCR, deployed by commit SHA | README, "Deploy" |

## 3. Roles and access

- **Role from the account:** each account has one role (`dispatcher`, `driver` or `crew`) in `profiles.role`. The app never offers a role choice at sign-in.
- **Two layers of checks:**
  - **The API:** it verifies the caller's Supabase JWT against the project's public signing keys (JWKS, ES256), then checks the role per endpoint. Without a valid token it returns 401; with the wrong role, 403.
  - **The database:** row-level security on every table that holds crew or driver data. Policies use `SECURITY DEFINER` helpers in the non-exposed `private` schema. The rules per role are in `schema.md`, "Row level security".
- **The cached role:** on a cold start the app opens the role's home screen from a cached profile so it works offline. It then re-checks `profiles` and signs out if the role changed or the account is gone (#116).

## 4. API

The full contract is `docs/openapi.json`, regenerated with `python -m app.contract --write`. The Android DTOs are tested against it (`OpenApiContractTest`).

| Role | Method and path | Purpose |
|---|---|---|
| Any | `GET /health` | Liveness (Azure's health check) |
| Dispatcher | `GET /pickup-requests?date=` | The day's pickups, with acknowledgement status |
| | `PATCH /pickup-requests/{id}` | Change a report time (flight delay) |
| | `GET /routes?date=` | The day's routes and stops |
| | `GET /vehicles` | Vans and status |
| | `PATCH /vehicles/{id}` | Set status: available, broken_down, unavailable |
| | `POST /optimisation-jobs` | Plan or re-plan: pickups, vans, trigger type. 202 Accepted |
| | `GET /optimisation-jobs/{id}` | Job status and the plan, with late and unassigned pickups |
| | `GET /messages?unread=` | Crew messages |
| | `POST /messages/{id}/ack` | Mark read |
| | `POST /messages/{id}/replies` | Reply with a dispatcher preset |
| Driver | `GET /drivers/me/route` | The current route, stop by stop |
| | `GET /drivers/me/routes` | Today's and upcoming routes |
| | `POST /drivers/me/pickup-events` | Upload a batch of pickup events |
| Crew | `GET /crew/me/pickup` | Next pickup, van, and pending change notices |
| | `POST /crew/me/notices/{id}/acknowledge` | Acknowledge a change |
| | `POST /messages` | Send a crew preset |
| Crew, dispatcher | `GET /preset-messages` | The presets the caller may send |

**Conventions:**
- **Errors:** every error is one `ErrorBody` with one `code` from `ErrorCode`, for example:
  - `not_plannable`;
  - `departed_routes`;
  - `already_confirmed`;
  - `idempotency_key_reused`.

  A request with several problems reports the first in a fixed order, documented per router.
- **Idempotency:** every write a phone might retry carries a key:
  - **Messages, replies and jobs:** an `Idempotency-Key` header. The same key and body return the original result; the same key with another body gets a 422.
  - **Pickup events:** each event has its own `idempotency_key`, so a repeat comes back as `duplicate`, not a second row.
- **Small payloads for 2G/3G:**
  - only the fields each screen needs;
  - no images;
  - lists paginated with a cursor (20 by default, at most 50);
  - pickup-event batches of 1 to 50 events, with the body capped at 32 KB (413).
- **Long work off the request:** `POST /optimisation-jobs` answers 202 at once. The solve runs in a solver process, because pure Python holds the GIL for its whole time limit, and the client polls `GET`. Run one uvicorn process: on start-up it fails any job left queued or running.

## 5. Data

The tables, constraints, relationships, triggers and RLS are in `docs/schema.md`, from the Chapter 4 ERD.

| Area | Tables |
|---|---|
| Core | `profiles`, `crew_members`, `vehicles`, `pickup_requests`, `optimization_jobs`, `optimization_job_pickups`, `routes`, `route_nodes`, `pickup_events`, `trip_records` |
| Communication | `preset_messages`, `crew_messages`, `message_replies`, `schedule_change_notices`, `device_tokens` |
| Validation and reference | `travel_time_observations` (logger), `pickup_zones` (the 28 zones) |

**Key rules:**
- **Locations are `GEOGRAPHY(Point, 4326)`,** and all distance queries use PostGIS in SQL. Haversine appears only inside the solver's in-memory loop.
- **Re-planning replaces routes.** Superseded route nodes are kept with `superseded_at`, so a late-synced offline event can still be judged against the plan it was made on.
- **A trigger moves the pickup's status.** `pickup_events_apply_to_pickup` updates the pickup request in the same transaction as the event. Drivers can't update pickups directly.

## 6. Planning and re-planning

- **The solver:** GA-ALNS, a steady-state GA whose mutation is one ALNS destroy-and-repair. Its fitness is tiered: crew first, then lateness, then late crew, then the buffer, ride, vans and time.
- **The design and its evaluation** are in `docs/solver_design.md` and `docs/results/`.
- **Travel time:** the worker predicts the whole week once from the Random Forest, every zone × weekday × hour. Legs between pickups come from the zone matrix (#106).
- **The RF's features:** zone, hour and weekday (cyclic), and the zone's position (#18). It is trained on the synthetic `trip_records.csv`, and its predictions are fingerprinted at image build (`RF_FINGERPRINT`).
- **Re-plans keep departed routes fixed,** except a broken-down van's. A re-plan takes whole routes, so a van never has two active routes.
- **Change notices:** each pickup whose time or van changed gets a `schedule_change_notices` row, which the crew member acknowledges.
- **Only the dispatcher starts a plan.** Messages never trigger one.

## 7. Offline pickup recording

- **The phone's outbox:** each driver action is written first to a Room table, with a client-made idempotency key and the time it happened on the device.
- **Upload:** a worker uploads in order, in batches, when there is a network. Each event's result is accepted, duplicate or rejected.
- **The guarantee:** at-least-once delivery from the phone, and exactly-once storage on the server through the keys.
- **Tested in #34:** 4,838 events through scripted network faults, with none lost and none stored twice. Seed 34 is replayed against real Postgres in CI (`docs/results/34-partition-test`).

## 8. Notifications

- **Crew see schedule changes on their next pickup read** (#53), as a "Pickup changed" card they acknowledge.
- **Push (FCM, #55) is parked for after the defence (#135).** `device_tokens` exists in the schema, and `schedule_change_notices.delivered_at` stays null until push is built.

## 9. Deployment and operations

- **Image:** built by GitHub Actions (`image.yml`) and pushed to GHCR as `acdos-api:<sha>`. The build trains the RF and fails if its fingerprint differs.
- **Hosting:** App Service pulls the image by SHA. It runs Always On, with a health check on `/health` and HTTPS only.
- **Secrets:** `DATABASE_URL` (the Supabase session pooler) is an app setting, entered by hand and never committed. Maps keys and the logger secret live in Edge Function secrets and Vault.
- **Fallback:** the backend run locally behind a Cloudflare quick tunnel (README).
- **Demo data:** `benchmarks/demo_seed` (`docs/demo_runbook.md`).

## 10. Quality

- **CI (`ci.yml`) on every PR:**
  - **Backend:** ruff lint and format, then pytest against Postgres with all migrations applied.
  - **Migrations:** applied in order to a clean database, then an RLS smoke test.
  - **Android:** ktlint, then build, unit tests and lint.
  - **Edge Functions:** checked in their own job.
- **Solver tests check feasibility:** every pickup visited once, capacity respected, and every deadline met or reported.
- **Conventions:** Conventional Commits (enforced by `.githooks/commit-msg`), one PR per issue, squash-merged.

## 11. Known limitations

- **Training data is synthetic** (L1 to L3). The logger's real observations are held out for validation only (MAPE 7.00%, #19).
- **All vans start from one depot.** There are no multi-trip vans, and crew already on board a broken-down van aren't re-planned (#135).
- **No push notifications** (#55).
- **The on-time results are under the RF model,** not measured on the road (#210).
