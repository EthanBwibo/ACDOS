# CLAUDE.md

Context for Claude Code sessions in this repo. Read this before changing anything.

## What this is

ACDOS: final-year capstone (Strathmore ICS Project II) for Kenya Airways crew ground
transport. It dispatches vehicles that pick crew up across Nairobi and deliver them to JKIA
before their rostered report time. The routing problem is a Capacitated Dynamic VRP with Time
Windows, many-to-one: many pickup origins, one destination (JKIA), a hard deadline per crew
member.

Out of scope: crew rostering, KCAA rest rules, CBA rules, ground handling staff. The roster is
a fixed external input.

Solo project. The student writes and must be able to explain every line at the defense, so
explain non-obvious decisions in the PR description and keep code readable over clever.

## Components and priority

1. **GA-ALNS solver** (`backend/app/solver/`): the research contribution. Genetic Algorithm
   population, with Shaw removal plus greedy re-insertion replacing mutation (Ropke and
   Pisinger, 2006). Fitness uses Random Forest journey time predictions.
2. **Random Forest journey time service** (`backend/app/ml/`): predicts pickup-to-JKIA
   duration from zone, hour, day of week and route corridor. Trained on `data/trip_records.csv`.
3. **Android client** (`android-client/`): three roles. Driver: three-tab bottom nav (Route,
   Schedule, Sync). Crew: two tabs (Pickup, Message). Dispatcher: hub and drill-down, no nav
   bar. Role comes from the account (Supabase Auth + RLS); never add a role selector at
   sign-in.
4. **Crew communication**: all messages routed through the dispatcher, preset messages only,
   no free text, no direct crew-driver chat. Crew can view pickup time and ETA and acknowledge
   changes. Messages never trigger re-optimisation. Priority events: flight delay, standby
   activation. Push via Firebase Cloud Messaging.
5. **Offline Event Sourcing sync**: demoted, built last if time allows. If it is cut, the cut
   must be documented, not silent.

## Layout

```
android-client/   Kotlin, package com.kq.acdos, Views (not Compose), minSdk 26
backend/app/      FastAPI: main.py, models/schemas.py, routers/, solver/, ml/
backend/migrations/  Supabase SQL migrations, numbered, one change per file
backend/tests/    pytest
data/             pickup_zones.csv (L1), temporal_calibration.csv (L2), trip_records.csv (L3),
                  jkia_reachability.csv (record of why the Rising & Campbell grid was rejected)
scripts/          generators for data/. Take the Maps API key as argv[1]
logger/           hourly Distance Matrix logger, stdlib only, run by GitHub Actions
docs/             design artefacts and chapter drafts
```

The `data-logger` branch holds only `travel_time_log.csv`, written hourly by the
`travel-time-logger` workflow. Never merge it into `main` and never commit to it by hand.

## Coding standards

**Python / FastAPI**
- Async endpoints. Every request and response body is a Pydantic model in `models/`.
- No distance or geography math in the API layer: use PostGIS (`ST_Distance`, `ST_DWithin`,
  geography type) in SQL. Haversine is acceptable only inside the solver's in-memory loop,
  with a comment saying why.
- Tests in `backend/tests/` with pytest. Solver changes need a test that checks feasibility:
  every pickup visited once, capacity respected, every deadline met or explicitly reported.
- Lint with ruff.

**Kotlin / Android**
- Coroutines for all async work; no callbacks, no blocking calls on the main thread.
- Room for local state. Retrofit with Moshi for the API.
- AGP 9 with built-in Kotlin; versions live in `gradle/libs.versions.toml`, never inline.

**Network payloads**
- Design for 2G/3G: small JSON, no images in API payloads, only the fields the screen needs,
  pagination on lists, idempotency keys on any write a driver might retry.

**Supabase**
- Schema changes only via files in `backend/migrations/`. No ad hoc changes in the dashboard.
- RLS on every table that holds crew or driver data.

## Data facts (do not get these wrong)

- Training data is synthetic, built in three layers: L1 live Google Distance Matrix baseline
  for 28 zones; L2 live hour and day multipliers (28 zones x 7 days x 17 hours); L3 15,000
  synthetic trips from L1 + L2 with lognormal noise (CV 10%).
- The Rising & Campbell (2017) grid is not used as numeric data. It was rejected (JKIA dead
  zone, flat-speed artifacts, pre-Expressway). Cited in literature only.
- Google Distance Matrix cannot query past departure times, so historical records cannot be
  pulled from it. That is why L3 is synthetic.
- Real validation data: the hourly logger, running since 20 October 2026.

## Data model decisions

The Chapter 4 class diagram and ERD are the source of truth for the schema. The table
definitions are in `docs/schema.md` (Table 4.1); migrations follow it, not the Pydantic models.
`trip_records` hang off `route_nodes` (`route_node_id`), not `routes`: each record is one crew
pickup leg, which is the unit the Random Forest predicts.

## Git workflow

- `main` is protected. Work on a branch prefixed by component: `solver/`, `rf/`, `android/`,
  `sync/`, `comms/`, `db/`, `docs/`, `ci/`.
- Conventional Commits, six types only: feat, fix, refactor, test, docs, chore. Format
  `type(scope): summary`, first line 72 characters max. Enforced by `.githooks/commit-msg`.
- One PR per issue, linked with `Closes #n`, squash-merged, branch deleted after.
- Never commit secrets: `.env`, `local.properties` and API keys stay out of git. GitHub
  Actions reads keys from repository secrets.
- Do not commit or push without the student's go-ahead.

## Environment

Windows machine. Backend venv at `backend/venv` (`backend\venv\Scripts\activate`). Supabase
and Firebase are not provisioned yet; the schema in the proposal is a design specification.
