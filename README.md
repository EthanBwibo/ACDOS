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
ACDOS/
├── android-client/   # Kotlin client (driver, crew, dispatcher)
├── backend/
│   ├── app/          # FastAPI: routers/, models/, solver/ (GA-ALNS), ml/ (Random Forest)
│   ├── migrations/   # Supabase SQL migrations
│   └── tests/
├── data/             # Layer 1-3 datasets: pickup zones, temporal calibration, trip_records
├── scripts/          # scripts that generated the data/ files
├── logger/           # hourly Distance Matrix logger (runs in GitHub Actions)
├── docs/             # design artefacts, diagrams, chapter drafts
├── .githooks/        # commit-msg hook enforcing Conventional Commits
└── .github/workflows/
```

## Setup

### Backend
```bash
cd backend
python -m venv venv
source venv/bin/activate  # or venv\Scripts\activate on Windows
pip install -r requirements.txt
uvicorn app.main:app --workers 1
```

The optimisation job API needs `DATABASE_URL` in `backend/.env`: Supabase's session pooler
(port 5432), as the `postgres` role. Keep `--workers 1`. On startup the backend marks any
job still `queued` or `running` as failed, since its solver process died with the last run.
That is only true with one uvicorn process: a second one would fail the first one's live
jobs. Solves run in a pool of `SOLVER_POOL_SIZE` processes (default 2), so one uvicorn
worker does not block on them.

### Android
Open `android-client/` in Android Studio. Gradle sync will pull Room, KSP, coroutines, and
Retrofit dependencies automatically.

### Database
Requires a Supabase project with the PostGIS extension enabled. Schema migrations live
in `backend/migrations/`.

## Deploy

The backend runs on Azure App Service (Azure for Students): Linux, plan B1, North Europe (next
to Supabase in eu-west-1), as one container built by Azure Container Registry from
`backend/Dockerfile` (#148). One uvicorn process with a solver pool of 2, Always On, health
check on `/health`, HTTPS only. Cost: about $13 a month for B1 plus about $5 for the registry
(Basic), taken from the student credit.

Run these in Git Bash from the repository root, signed in with `az login`. `ACR` and `APP` must
be globally unique; the app's address is printed by `az webapp show` at the end.

```bash
RG=acdos-rg LOC=northeurope PLAN=acdos-plan ACR=<registry> APP=<app> TAG=$(git rev-parse --short HEAD)

# Once: the resource group, the registry and the plan.
az group create -n $RG -l $LOC
az acr create -g $RG -n $ACR --sku Basic
az appservice plan create -g $RG -n $PLAN --is-linux --sku B1

# Build the image in Azure (no local Docker). The log prints "rf fingerprint: ...":
# it must equal `cd backend && python -m app.ml.fingerprint` run locally.
az acr build -r $ACR -t acdos-api:$TAG -f backend/Dockerfile .

# Once: the app, pulling from the registry with its managed identity.
az webapp create -g $RG -p $PLAN -n $APP --assign-identity '[system]' \
  --container-image-name $ACR.azurecr.io/acdos-api:$TAG
az role assignment create --role AcrPull \
  --assignee $(az webapp identity show -g $RG -n $APP --query principalId -o tsv) \
  --scope $(az acr show -n $ACR --query id -o tsv)
az webapp config set -g $RG -n $APP --always-on true \
  --generic-configurations '{"acrUseManagedIdentityCreds": true, "healthCheckPath": "/health"}'
az webapp update -g $RG -n $APP --https-only true
az webapp config appsettings set -g $RG -n $APP --settings WEBSITES_PORT=8000 SOLVER_POOL_SIZE=2
```

`DATABASE_URL` is set by hand, never committed: Supabase dashboard, Connect, **Session
pooler** (port 5432), as `postgres`. Type it in your own terminal:

```bash
az webapp config appsettings set -g $RG -n $APP --settings DATABASE_URL='<session pooler URL>'
```

Redeploy after a change: build a new tag, point the app at it, check it.

```bash
TAG=$(git rev-parse --short HEAD)
az acr build -r $ACR -t acdos-api:$TAG -f backend/Dockerfile .
az webapp config container set -g $RG -n $APP --container-image-name $ACR.azurecr.io/acdos-api:$TAG
curl https://$(az webapp show -g $RG -n $APP --query defaultHostName -o tsv)/health
```

The app's HTTPS address goes in `android-client/local.properties` as `api.baseUrl=https://...`.

### After the defence

Stopping the app (`az webapp stop`) does **not** stop the bill: the B1 plan and the registry
charge whether the app runs or not. To stop all charges, delete the resource group, which
deletes the app, the plan and the registry together (Supabase is not in it):

```bash
az group delete -n acdos-rg --yes
```

### Demo-day fallback: run locally behind a Cloudflare quick tunnel

If the Azure app is down, run the backend on the laptop and give the phone a public HTTPS
address with a Cloudflare quick tunnel (no Cloudflare account; the address changes every
run, so this is for the demo only).

```bash
# Once: winget install --id Cloudflare.cloudflared
cd backend && venv\Scripts\activate         # DATABASE_URL in backend/.env, as in Setup
uvicorn app.main:app --workers 1 --port 8000
# In a second terminal:
cloudflared tunnel --url http://localhost:8000
```

`cloudflared` prints `https://<random words>.trycloudflare.com`. Check
`https://<that address>/health`, put it in `android-client/local.properties` as
`api.baseUrl=...`, and rebuild the app. The laptop must stay awake and online for the demo.

## Data note

Real Kenya Airways trip-log data was not confirmed available within the project timeline.
Training data for the Random Forest service is a synthetic dataset calibrated against live
Google Distance Matrix queries across 28 Nairobi pickup zones and a full weekday/hour
temporal grid — documented in `docs/`.

A held-out set of real observations is being collected for validation: `logger/` queries
Google Distance Matrix hourly for all 28 zones (from 20 October 2026) and appends the
results to `travel_time_log.csv` on the `data-logger` branch.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for branch naming, commit conventions, and the
PR workflow.

## Status

Active development — see the [project board](../../projects) and milestones for current
progress against M1–M8.

## Supervision

Strathmore University, School of Computing and Engineering Sciences.
Supervisor: Allan Vikiru.
