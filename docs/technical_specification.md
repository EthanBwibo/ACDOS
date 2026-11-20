# ACDOS technical specification

This specification is compiled from the README, `docs/openapi.json` (the API contract) and `docs/schema.md` (Table 4.1). Where those files go into detail, this document points to them rather than copying them. If this document and those sources disagree, the sources win.

## 1. Purpose and scope

ACDOS dispatches vans that collect Kenya Airways flight crew across Nairobi and deliver them to JKIA before their rostered report time. It also re-plans after a flight delay or a vehicle breakdown. Standby activation is in the schema and API but not supported yet: no screen sends it.

**In scope:**
- getting crew pickups in: a roster CSV import, or one pickup at a time;
- planning and re-planning pickups, one wave of crew at a time, with vans reused from wave to wave;
- journey-time prediction;
- driver pickup recording that works offline;
- preset messaging between crew and the dispatcher;
- a phone call between a crew member and their driver around the pickup.

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
- **Each role's home screen** has a bottom nav bar:
  - **Driver:** Route, Schedule, Sync. The Route tab shows the next route with crew still to collect, on an osmdroid map (#235), with Navigate to the next stop in Google Maps (#236) and a Call button on a stop (#255).
  - **Crew:** Pickup, Message. The Pickup tab has a Call button for the driver (#255); messages show as chat bubbles (#226).
  - **Profile (driver and crew, #231):** opened from the overflow menu, not a tab. It is read-only and cached in Room, so it opens offline. Crew see their name, crew role, home zone and next pickup; drivers see their name and their van's plate, seats and status. Sign out and the theme are there too. Nothing can be edited: the roster is the source of truth for the home location, and the RF knows only the 28 zones, so a self-set pin would be snapped to a zone and could get a wrong journey time.
  - **Profile (dispatcher, #249):** from the overflow menu too: the signed-in email, Sign out and the theme.
  - **Dispatcher** (#230): five tabs, each holding related screens:

    | Tab | Holds |
    |---|---|
    | Overview | the day's stats and plan state, alerts (breakdowns, flight delays, unread messages), and the day picker every tab follows |
    | Plan | the day's unplanned pickups grouped into waves, the van picker and the optimisation run; Re-plan opens here |
    | Routes | the day's routes, each opening its detail and map |
    | Fleet & crew | Pickups (with Import roster, the roster template and Add pickup), Vehicles, and Crew (search, then a crew member's home zone and Set home) |
    | Messages | an inbox per crew member, with preset replies |

    Overview's tiles open the matching list (#248). A drill-down (a route, Re-plan, Import roster, Add pickup, a crew member) opens inside its tab with a back arrow, and the nav bar stays. Each tab keeps its own back stack. A tab that isn't selected is stopped, so a crew message counts as read only while Messages is on screen. The dispatcher app is online only.

## 4. API

The full contract is `docs/openapi.json`, regenerated with `python -m app.contract --write`. The Android DTOs are tested against it (`OpenApiContractTest`).

| Role | Method and path | Purpose |
|---|---|---|
| Any | `GET /health` | Liveness (Azure's health check) |
| Dispatcher | `GET /pickup-requests?date=` | The day's pickups, with acknowledgement status |
| | `POST /pickup-requests` | Add one pickup, from home or a map pin (#253) |
| | `PATCH /pickup-requests/{id}` | Change a report time (flight delay) |
| | `POST /roster-imports` | Import a roster CSV: a dry run, then the import (#229) |
| | `GET /crew-members?q=` | Search crew by name or staff number, 20 a page (#253) |
| | `PATCH /crew-members/{id}/home` | Set a crew member's home from a map pin (#253) |
| | `GET /pickup-zones/nearest?lat=&lon=` | The nearest zone to a pin, and whether it is inside the zones (#253) |
| | `GET /routes?date=` | The day's routes and stops |
| | `GET /vehicles` | Vans and status |
| | `PATCH /vehicles/{id}` | Set status: available, broken_down, unavailable |
| | `POST /optimisation-jobs` | Plan or re-plan one wave: pickups, vans, trigger type. 202 Accepted |
| | `GET /optimisation-jobs/{id}` | Job status and the plan, with late and unassigned pickups and the vans left out |
| | `GET /messages?unread=` | Crew messages |
| | `POST /messages/{id}/ack` | Mark read |
| | `POST /messages/{id}/replies` | Reply with a dispatcher preset |
| Driver | `GET /drivers/me` | The assigned van: plate, seats, status (Profile, #231) |
| | `GET /drivers/me/route` | The next route with crew still to collect, stop by stop, with a crew member's number in the call window |
| | `GET /drivers/me/routes` | Today's and upcoming routes |
| | `POST /drivers/me/pickup-events` | Upload a batch of pickup events |
| Crew | `GET /crew/me` | Crew role and home zone (Profile, #231) |
| | `GET /crew/me/pickup` | Next pickup, van, driver's first name (and number in the call window), and pending change notices |
| | `POST /crew/me/notices/{id}/acknowledge` | Acknowledge a change |
| | `POST /messages` | Send a crew preset |
| Crew, dispatcher | `GET /preset-messages` | The presets the caller may send |

**Conventions:**
- **Errors:** every error is one `ErrorBody` with one `code` from `ErrorCode`, for example:
  - `not_plannable`;
  - `departed_routes`;
  - `planning_window_too_wide` (a job spanning more than one wave, #268);
  - `outside_pickup_zones`, `report_time_past`, `duplicate_pickup` (the roster import's reasons, shared by Add pickup);
  - `already_confirmed`;
  - `idempotency_key_reused`.

  A request with several problems reports the first in a fixed order, documented per router.
- **Idempotency:** every write a phone might retry carries a key:
  - **Messages, replies, jobs, roster imports and added pickups:** an `Idempotency-Key` header. The same key and body return the original result; the same key with another body gets a 422.
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
| Core | `profiles`, `crew_members`, `vehicles`, `pickup_requests`, `optimization_jobs`, `optimization_job_pickups`, `optimization_job_left_out_vehicles`, `routes`, `route_nodes`, `pickup_events`, `trip_records` |
| Intake | `roster_imports` (one row per import, by its key) |
| Communication | `preset_messages`, `crew_messages`, `message_replies`, `schedule_change_notices`, `device_tokens` |
| Validation and reference | `travel_time_observations` (logger), `pickup_zones` (the 28 zones) |

**Key rules:**
- **Locations are `GEOGRAPHY(Point, 4326)`,** and all distance queries use PostGIS in SQL. Haversine appears only inside the solver's in-memory loop.
- **Re-planning replaces routes.** Superseded route nodes are kept with `superseded_at`, so a late-synced offline event can still be judged against the plan it was made on.
- **Phone numbers are never read from a table** (#255, migration 036). `profiles.phone` and `crew_members.phone` have SELECT revoked from `anon` and `authenticated`, so a PostgREST select of them is a permission error. Two `security definer` functions in `private` give a number only to the other party of a planned pickup, from 30 minutes before it until it is picked up, missed or cancelled.
- **A trigger moves the pickup's status.** `pickup_events_apply_to_pickup` updates the pickup request in the same transaction as the event. Drivers can't update pickups directly.

## 6. Planning and re-planning

- **The solver:** GA-ALNS, a steady-state GA whose mutation is one ALNS destroy-and-repair. Its fitness is tiered: crew first, then lateness, then late crew, then the buffer, ride, vans and time.
- **The design and its evaluation** are in `docs/solver_design.md` and `docs/results/`.
- **Travel time:** the worker predicts the whole week once from the Random Forest, every zone × weekday × hour. Legs between pickups come from the zone matrix (#106).
- **The RF's features:** zone, hour and weekday (cyclic), and the zone's position (#18). It is trained on the synthetic `trip_records.csv`, and its predictions are fingerprinted at image build (`RF_FINGERPRINT`).
- **One plan is one wave** (#268, #270). The server refuses a job whose pickups' report times span more than 4 h (`PLANNING_WINDOW`) with 422 `planning_window_too_wide`. The Plan tab groups the day's pickups into waves first: a gap of more than 60 minutes, or a span over 4 h, starts a new wave. The reason: the solver has a deadline per crew member but no earliest pickup, so a whole day planned at once collected all 120 defence-day crew before 05:30, some 19 h early (`docs/defence_evidence.md`, section 4).
- **Vans are reused across waves** (#274). For a ticked van, a route on the wave's day is:
  - **earlier** if it reaches JKIA before the wave's earliest report time and its crew all report before it: it is kept, and the van starts at JKIA, free 15 minutes (`REUSE_TURNAROUND`) after that route is due in;
  - **later** if it leaves after the wave's latest report time and its crew all report after it: it is kept, and the van is left out of the job and listed in the job's result;
  - **overlapping** otherwise: replaced, as before.

  Only overlapping routes' pickups join a job, and only they count towards the 4 h limit. The solver itself is unchanged: a vehicle already had a start point and an earliest start. The Plan tab marks vans already on a wave and shows the left-out list after Start (#272, #276).
- **Re-plans keep departed routes fixed,** except a broken-down van's. A re-plan takes whole routes, so a van never has two routes in one wave.
- **Change notices:** each pickup whose time or van changed gets a `schedule_change_notices` row, which the crew member acknowledges.
- **Only the dispatcher starts a plan.** Messages never trigger one.

## 7. Offline pickup recording

- **The phone's outbox:** each driver action is written first to a Room table, with a client-made idempotency key and the time it happened on the device.
- **Upload:** a worker uploads in order, in batches, when there is a network. Each event's result is accepted, duplicate or rejected.
- **The guarantee:** at-least-once delivery from the phone, and exactly-once storage on the server through the keys.
- **Tested in #34:** 4,838 events through scripted network faults, with none lost and none stored twice. Seed 34 is replayed against real Postgres in CI (`docs/results/34-partition-test`).

## 8. Notifications

- **Push notifications are not built** (#55, cut for the defence and kept for after it under #135). Nothing is sent to a phone: Firebase Cloud Messaging is not set up.
- **Crew see changes when the app refreshes:** on opening the Pickup tab or pulling to refresh, a changed pickup shows as a "Pickup changed" card they acknowledge (#53). Drivers see a re-planned route the same way, by refreshing the Route tab. Messages and preset replies also arrive on refresh.
- `device_tokens` exists in the schema, and `schedule_change_notices.delivered_at` stays null until push is built.

## 9. Deployment and operations

- **Image:** built by GitHub Actions (`image.yml`) and pushed to GHCR as `acdos-api:<sha>`. The build trains the RF and fails if its fingerprint differs.
- **Hosting:** App Service pulls the image by SHA. It runs Always On, with a health check on `/health` and HTTPS only.
- **Secrets:** `DATABASE_URL` (the Supabase session pooler) is an app setting, entered by hand and never committed. Maps keys and the logger secret live in Edge Function secrets and Vault.
- **Fallback:** the backend run locally behind a Cloudflare quick tunnel (README).
- **Demo data:** `benchmarks/demo_seed` for the demo morning, `scripts/seed_test_accounts.py` for the accounts and `scripts/make_defence_day.py` for the 120-crew defence day (`docs/demo_runbook.md`).
- **Deployed at the freeze:** image `acdos-api:94775ca…` with migrations 000 to 037 (`docs/defence_evidence.md`).

## 10. Quality

- **CI (`ci.yml`) on every PR:**
  - **Backend:** ruff lint and format, then pytest against Postgres with all migrations applied.
  - **Migrations:** applied in order to a clean database, then an RLS smoke test.
  - **Android:** ktlint, then build, unit tests and lint.
  - **Edge Functions:** checked in their own job.
- **Solver tests check feasibility:** every pickup visited once, capacity respected, and every deadline met or reported.
- **Conventions:** Conventional Commits (enforced by `.githooks/commit-msg`), one PR per issue, squash-merged.

## 11. Known limitations

The full list, with the evidence behind each, is in `docs/defence_evidence.md`, section 5.

- **Training data is synthetic** (L1 to L3). The logger's real observations are held out for validation only (MAPE 7.00%, #19).
- **No push notifications** (#55): crew and drivers see changes when the app refreshes.
- **The solver has no earliest pickup time.** One wave per plan (4 h) keeps crew from being collected hours early.
- **Vans have no position.** A van starts at the depot, or at JKIA when reused from an earlier wave. There is no GPS, so the driver's ETA is always empty (#171, #182).
- **Van reuse needs waves planned in order.** A van with a later route is left out of an earlier wave's job, not fitted around it.
- **Crew already on board a broken-down van aren't re-planned** (#135).
- **The on-time results are under the RF model,** not measured on the road (#210).
