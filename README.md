# ACDOS — Autonomous Crew Mobility and Dynamic Optimization System

Final-year ICS Project II capstone (Strathmore University) addressing Kenya Airways flight
crew ground transport: getting pilots and cabin crew from pickup points across Nairobi to
JKIA by their rostered duty report time, under a fleet of capacity-constrained vehicles and
unpredictable Nairobi traffic.

## Problem

Crew ground transport is currently dispatched via static, manually generated vehicle
schedules that cannot adapt to flight delays, standby crew activations, or vehicle
breakdowns in real time. ACDOS replaces this with a continuously re-optimising dispatch
platform.

## Architecture — three pillars

| Pillar | Component | Purpose |
|---|---|---|
| 1 | **GA-ALNS Solver** | Genetic Algorithm + Adaptive Large Neighbourhood Search (Shaw removal, greedy re-insertion) solving the Capacitated Dynamic VRP with Time Windows (CDVRPTW) — many-to-one pickup topology, JKIA as single depot |
| 2 | **Random Forest Journey Time Service** | Predicts pickup-to-JKIA travel duration from time-of-day, day-of-week, and route corridor features; feeds calibrated estimates into the solver's fitness function at runtime |
| 3 | **Offline Event Sourcing Sync** | Android-side write-ahead log of pickup confirmations; survives 2G/3G network partitions with at-least-once delivery and server-side idempotency on reconnect |

## Tech stack

- **Android client:** Kotlin, coroutines, Room, Retrofit — targets API 26+
- **Backend:** Python, FastAPI, Pydantic-typed request/response schemas
- **Database:** Supabase (PostgreSQL) with PostGIS for all spatial-distance calculations
- **Methodology:** Agile Scrum, two-week sprints

## Repo structure

```
acdos/
├── android/          # Kotlin client
├── backend/          # FastAPI app, GA-ALNS solver, RF service
├── docs/             # design artefacts, diagrams, chapter drafts
├── data/             # pickup zones, calibration data, trip_records pipeline
└── .github/
```

## Setup

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Android
Open `android/` in Android Studio. Gradle sync will pull Room, KSP, coroutines, and
Retrofit dependencies automatically.

### Database
Requires a Supabase project with the PostGIS extension enabled. Schema migrations live
in `backend/migrations/`.

## Data note

Real Kenya Airways trip-log data was not confirmed available within the project timeline.
Training data for the Random Forest service is a synthetic dataset calibrated against live
Google Distance Matrix queries across 28 Nairobi pickup zones and a full weekday/hour
temporal grid — documented in `docs/`.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for branch naming, commit conventions, and the
PR workflow.

## Status

Active development — see the [project board](../../projects) and milestones for current
progress against M1–M8.

## Supervision

Strathmore University, School of Computing and Engineering Sciences.
Supervisor: Allan Vikiru.
