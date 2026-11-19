# Defence evidence: issues and PRs #225 to #277

What changed between 15 and 19 November 2026, ahead of the code freeze and the `v1.0-defence`
tag. Every number from #225 to #277 is listed: 28 issues and 25 pull requests. All 25 PRs are
squash-merged into `main`, and every issue is closed except #256, which this file belongs to.

State at the time of writing (19 November 2026):

| | |
|---|---|
| `main` | `c6bcf10` (#277) |
| Azure image | `ghcr.io/ethanbwibo/acdos-api:94775ca77779d7de481debf0c0d44a2900ce27df` (#275). #273 and #277 change only the Android client, so the backend on `main` is the same as this image. |
| Supabase migrations | 000 to 037 applied (`list_migrations`); this period added 031 to 037 |
| Backend tests | 1,139 passed in CI on `main` (`c6bcf10`), with CI's PostGIS, so the Postgres tests run too |
| Android unit tests | 443 passed, 0 failed, on `main` (`c6bcf10`), run locally; CI also runs them with `lintDebug` and ktlint 1.8.0 |
| Edge Function tests | 6 passed (Deno, CI) |

## 1. Issues and the PRs that closed them

| Issue | Title | Closed by |
|---|---|---|
| #225 | Remove the extra space under the bottom nav | #233 |
| #226 | Chat bubbles for crew and dispatcher messages | #234 |
| #227 | Real route map with osmdroid | #235 |
| #228 | Navigate to the next stop in Google Maps | #236 |
| #229 | Roster CSV import for the dispatcher | #237 (backend), #238 (Android); #239 follow-up |
| #230 | Bottom nav for the dispatcher | #241 |
| #231 | Read-only profile for crew and driver | #243 (backend), #244 (Android) |
| #232 | Preset message to request a pickup address change | #242 |
| #245 | Optional pickup location pasted from Google Maps, with a zone preview | #246 (backend), #247 (Android) |
| #248 | Overview tiles open their screens; Retry only for network errors | #258 |
| #249 | Dispatcher profile | #259 |
| #250 | Per-crew inbox on dispatcher Messages | #262 |
| #251 | Demo accounts | #257 |
| #252 | Defence dataset: about 120 crew, 20 vans, five time bands | #260 |
| #253 | Add pickup form and Set home with a map pin | #263 (backend), #264 (Android) |
| #254 | Roster template download and tolerant headers | #261 (backend), #266 (Android) |
| #255 | Driver and crew contact: names, plate, call buttons | #265 (backend), #267 (Android) |
| #256 | Update the technical spec, user guide and runbook | open: this file is its first part |
| #268 | Refuse a plan whose report times span more than one wave | #269 |
| #270 | Plan the day wave by wave on the Plan tab | #271 |
| #272 | Van picker marks vans already on a wave | #273 |
| #274 | Reuse vans across waves | #275 |
| #276 | Van reuse across waves in the picker, re-plan and driver screens | #277 |

#240 has no issue of its own: it fixed a Supabase security advisor warning.

## 2. Pull requests

Each row gives the merge commit, what changed and how it was tested. "CI" means the GitHub
Actions jobs (backend with PostGIS, Android build, unit tests and lint, Edge Functions,
migrations on plain Postgres, image build); every PR below merged with them green.

### 15 to 17 November: interface and roster import

| PR | Merged | What changed | Tests |
|---|---|---|---|
| #233 `57e3a1d` | 15 Nov | The bottom nav took the navigation bar inset twice. `applySystemBarPadding` now gives the bottom inset to the bar on screens that have one, and consumes the insets. | `SystemBarPaddingTest` (Robolectric): bar and root insets, with and without the keyboard and a bar. |
| #234 `63ad134` | 16 Nov | Chat bubbles for crew and dispatcher messages, with the sender's own on the right. | `ChatAdapterTest`, `ChatTimelineTest`: sides per role, names, "Seen" line, day headers, ordering with replies. |
| #235 `20cf9a1` | 16 Nov | Real route map with osmdroid, replacing the drawn projection. | `RouteMapTest`: line through the stops then JKIA, marker colours per status, recentre, OSM credit. |
| #236 `5546b74` | 16 Nov | Navigate to the next stop in Google Maps, falling back to any `geo:` app. | `NavigationTest`: Google Maps first, fallback, locale-safe coordinates, no maps app. |
| #237 `db2f8d2` | 16 Nov | Roster CSV import for the dispatcher: `POST /roster-imports` with a dry run, per-line reject reasons and an idempotency key. Migrations 031 (crew `staff_no`) and 032 (`roster_imports`). | `test_roster.py` (21) and `test_roster_imports_postgres.py` (CI). |
| #238 `50a208b` | 16 Nov | Android: Import roster on the Pickups screen, dry run first, then import with a key. | `RosterImportViewModelTest` (8): dry run, key reuse on retry, new key per file. |
| #239 `d868b13` | 16 Nov | Script that regenerates `docs/roster_sample.csv` from tomorrow, so the sample's dates never go stale. | `test_roster_sample.py` (3), including that the checked-in file is what the script writes. |
| #240 `a5c801f` | 16 Nov | Migration 033: revoke execute on `rls_auto_enable()` from `anon` and `authenticated`. | Applied and checked on Supabase: ACL, RLS still enabled on a new table, advisor warning gone. |
| #241 `352a073` | 16 Nov | Bottom nav for the dispatcher: Overview, Plan, Routes, Fleet & crew, Messages, each with its own back stack. | `DispatcherTabsTest` (3): mark-read only on Messages, per-tab back stacks, reselect. |
| #242 `1401e75` | 17 Nov | Crew preset "I need to change my pickup address". Migration 034. | `test_messages_postgres.py` (CI): offered to crew only, reaches the dispatcher, starts no job, changes no address. |
| #243 `b02d1dd` | 17 Nov | `GET /crew/me` (role, home zone) and `GET /drivers/me` (van) for the profile screen. | `test_driver_crew_reads_postgres.py` (CI): fields, no van, 403s, and that the RLS policies are needed. |
| #244 `e4ebce6` | 17 Nov | Read-only Profile for crew and drivers, from the overflow menu, with Sign out. | `ProfileRepositoryTest`, `ProfileRowsTest`. |
| #246 `75a1e26` | 17 Nov | Roster: optional pickup location, pasted from Google Maps in any of its formats. | `test_roster.py`: 11 accepted formats, 9 refused values; `test_roster_imports_postgres.py` (CI). |

### 18 November: defence plan items 4 to 8

| PR | Merged | What changed | Tests |
|---|---|---|---|
| #247 `54b4711` | 18 Nov | Android: the roster preview shows each pickup point's zone and distance before importing. | `RosterLocationRowsTest`. |
| #257 `948ddfb` | 18 Nov | Demo accounts: named crew logins, a second dispatcher, a driver per van (`seed_test_accounts.py`). | `test_demo_accounts.py` (8). |
| #258 `5b6fe3b` | 18 Nov | Overview tiles open their screens; Retry is offered only for network errors. | `DispatcherTabsTest`, `RosterImportViewModelTest`. |
| #259 `1f11246` | 18 Nov | Dispatcher profile from the overflow menu. Room version 6 adds the email. | `ProfileRepositoryTest`, `ProfileRowsTest`, `AcdosDatabaseMigrationTest`, `DispatcherTabsTest`. |
| #261 `b5b6b2b` | 18 Nov | Roster template (`docs/acdos_roster_template.csv`) and tolerant headers: case, spaces, `-`/`_` and aliases; a duplicate column is refused. | `test_roster.py`. |
| #262 `1882637` | 18 Nov | Per-crew inbox on the dispatcher's Messages tab. | `CrewThreadsTest`, `InboxViewModelTest`. |

### 19 November: add pickup, contacts, waves and van reuse

| PR | Merged | What changed | Tests |
|---|---|---|---|
| #263 `f29e1ed` | 19 Nov | `GET /crew-members` (search, 20 a page), `GET /pickup-zones/nearest`, `POST /pickup-requests` (idempotent) and `PATCH /crew-members/{id}/home`. Migration 035 (idempotency key on pickups). | `test_manual_postgres.py` (CI), contract cases for every error code. |
| #264 `d77286a` | 19 Nov | Android: Add pickup form, Crew list under Fleet & crew, Crew detail with Set home on a map pin. Nearest zone is asked once per pin placement, never while dragging. | `PickupEntryViewModelTest` (13). |
| #265 `5e25dfa` | 19 Nov | Contact numbers for the Call buttons. Migration 036: `phone` on profiles and crew_members, SELECT revoked on both columns, numbers only through two `security definer` functions, from 30 min before the pickup until it is done. | `test_contacts_postgres.py` (CI): window, done statuses, unrelated users, and a permission error on a direct PostgREST-style select. |
| #266 `b7f7903` | 19 Nov | Android: download the roster template from Pickups. | `RosterTemplateTest`. |
| #267 `37f9092` | 19 Nov | Android: call the driver (crew) or crew member (driver) around the pickup. Numbers are held in memory only. | `CrewPickupRepositoryTest`, `DriverRouteRepositoryTest`. |
| #260 `67fe4a4` | 19 Nov | Defence dataset: 120 crew, 20 vans, five time bands (`make_defence_day.py`: roster, seed, plan, reset), with `plan --whole-day` for the timing in section 3. | `test_defence_day.py`, `test_defence_day_postgres.py` (CI). |
| #269 `e811e26` | 19 Nov | `POST /optimisation-jobs` refuses a job whose pickups' report times span more than 4 h (`PLANNING_WINDOW`), with 422 `planning_window_too_wide`. | `test_optimisation_jobs.py`: 4 h 55 min refused, exactly 4 h accepted; contract case. |
| #271 `15a1b7e` | 19 Nov | Android: the Plan tab groups unplanned pickups into waves (a gap over 60 min, or a span over 4 h, starts a new one) and plans one at a time. | `PlanWavesTest`, including that the defence day gives exactly its five bands. |
| #275 `94775ca` | 19 Nov | Van reuse across waves (section 4). Migration 037 (`optimization_job_left_out_vehicles`). The driver's current route is the next one with crew still to collect. | `test_van_reuse_postgres.py` (CI): reuse across two waves, an overlapping route still replaced, a later route's van left out and listed, the driver's route moving on. In-memory API tests for the JKIA start and the left-out list. |
| #273 `abb3fdf` | 19 Nov | Android: the van picker marks vans already on a wave, unticked by default. | `PlanWavesTest`, `DispatcherViewModelTest`. |
| #277 `c6bcf10` | 19 Nov | Android: van reuse in the picker, re-plan and driver screens, including the left-out list after Start. | `PlanWavesTest.routeKind` against #275's Postgres cases. |

## 3. Migrations

| Migration | PR | What it does |
|---|---|---|
| 031 `add_crew_staff_no` | #237 | `crew_members.staff_no`, unique, for matching roster rows |
| 032 `create_roster_imports` | #237 | `roster_imports`: one row per import, keyed by its idempotency key |
| 033 `revoke_rls_auto_enable_execute` | #240 | API roles can no longer execute `rls_auto_enable()` |
| 034 `add_change_pickup_address_preset` | #242 | The crew preset `change_pickup_address` |
| 035 `add_pickup_request_idempotency` | #263 | `pickup_requests.idempotency_key` (unique) and `request_hash`, set together |
| 036 `add_contact_phones` | #265 | Phone columns; column-level SELECT; `private.driver_contact` and `private.crew_phone` |
| 037 `create_optimization_job_left_out_vehicles` | #275 | Vans a job left out, with the later route's times; RLS for the dispatcher |

Each was checked against `list_migrations` before its number was used, and applied on
Supabase after its PR merged.

## 4. Planning timings and van reuse

All runs: live Supabase and the Azure API, `make_defence_day.py` for 20 November 2026, 120
crew, 20 vans of 14 seats, Random Forest travel times (Azure sets no `TRAVEL_MODEL`, so the
default `rf` applies). Each time is
from the POST to the job reading `completed`. One run each; the dataset was reset afterwards.

### Per band, separate vans per band (#260, image `b5b6b2b`)

| Band | Report times | Pickups | Vans | Solve | Routes | Late | Unassigned |
|---|---|---:|---:|---:|---:|---:|---:|
| early | 04:00–06:30 | 42 | 7 | 30.7 s | 7 | 0 | 0 |
| mid | 08:00–10:00 | 24 | 4 | 18.8 s | 4 | 0 | 0 |
| noon | 11:30–13:30 | 18 | 3 | 19.0 s | 3 | 0 | 0 |
| afternoon | 15:00–17:30 | 18 | 3 | 19.0 s | 3 | 0 | 0 |
| night | 20:00–23:00 | 18 | 3 | 19.1 s | 3 | 0 | 0 |

All five one after another: 106.6 s.

### The whole day as one job (#260)

120 pickups and 20 vans, completed in 22.4 s: 9 routes, 0 late, 0 unassigned. But the plan
is unusable: all 9 vans reach JKIA between 03:44 and 05:30, so crew reporting at 23:00 would
arrive 18.9 h early. The solver enforces each crew member's deadline but has no earliest
pickup, so "0 late" says nothing about this. #269 now refuses such a job, and #271 plans the
day wave by wave.

The 230 s limit on an Azure App Service request does not apply: `POST /optimisation-jobs`
answers 202 at once and the solve runs in a separate process. The app polls every 2 s for up to
180 s; the slowest job here took 30.7 s.

### Van reuse, every wave with all 20 vans, in order (#275, image `94775ca`)

| Wave | Pickups | Vans used | Reused from an earlier wave | Left out | Solve | Late / unassigned |
|---|---:|---:|---:|---:|---:|---|
| early | 42 | 9 | 0 | 0 | 31.0 s | 0 / 0 |
| mid | 24 | 7 | 7 | 0 | 21.4 s | 0 / 0 |
| noon | 18 | 6 | 5 | 0 | 21.1 s | 0 / 0 |
| afternoon | 18 | 5 | 5 | 0 | 20.9 s | 0 / 0 |
| night | 18 | 6 | 6 | 0 | 20.8 s | 0 / 0 |

10 distinct vans over the day instead of 20; four of them (KDX 001–004) ran in every wave.
Checked in the database: every reused van leaves JKIA at least 21 min after its previous
route is due in (the turnaround is 15 min), and no van's routes clash.

How reuse decides, for a ticked van and a wave (the span of the job's report times):

| A route of the van on the wave's day | is | and the van |
|---|---|---|
| in at JKIA before the wave's earliest report time, its crew all reporting before it | earlier: kept | starts at JKIA, free 15 min (`REUSE_TURNAROUND`) after the latest such route is due in |
| leaving after the wave's latest report time, its crew all reporting after it | later: kept | is left out of the job and listed in the result |
| anything else | overlapping: replaced as before | is planned from the depot, or is refused (409) if that route has left |

## 5. Limitations

1. **No push notifications (#55).** Firebase Cloud Messaging is not built. Crew see a
   changed pickup, and drivers a changed route, when the app refreshes. Messages and replies
   also arrive on refresh.
2. **The solver has no earliest pickup time.** It enforces each crew member's report time as
   a deadline only. A plan that spans a whole day collects everyone too early (section 4);
   the 4 h guard (#269) and planning wave by wave (#271) prevent it, rather than the solver.
3. **The wave limit is a fixed 4 h,** and waves are grouped on the phone (a gap over 60 min
   starts a new one). A roster whose report times run continuously with no gap is split
   at 4 h.
4. **Van reuse relies on planning waves in order.** A van with a later route is left out of
   an earlier wave's job, not fitted around that route. Whether a reused van is free early
   enough is left to the solver, which uses other vans or reports pickups late.
5. **Vans have no position.** A van starts at the depot, or at JKIA when reused. There is no
   GPS, so a driver's ETA is always empty (#171, #182).
6. **Nothing marks a route completed.** A route counts as finished when all its stops are
   picked up, missed or cancelled, so the driver's screen moves to the next route then, before
   the van has reached JKIA.
7. **Contact is by phone call only,** from 30 minutes before the scheduled pickup until it is
   done. There is no chat between crew and drivers; every message goes through the dispatcher.
   Numbers must be Kenyan mobiles.
8. **Crew pickup details are incomplete (#182):** the zone label, the van's description, the
   flight number in a delay notice and the driver's live ETA are not in the API.
9. **Travel-time training data is synthetic** (Layer 3), built from live Google Distance
   Matrix baselines and hourly multipliers. The hourly logger's records are held-out
   validation only.
10. **One API process.** A job still queued or running when the backend restarts is marked
    failed at startup and must be started again.
11. **Timings are single runs** on the deployed Azure plan, not repeated measurements.
12. **Database tests run in CI only.** They need a throwaway PostGIS database and never run
    against Supabase.
13. **On-device checks** listed as still to do in the Android PRs (#233, #258, #259, #266)
    were left to the student's phone.
14. **Supabase Auth:** the security advisor still reports leaked password protection as
    disabled, a dashboard setting (#240).
