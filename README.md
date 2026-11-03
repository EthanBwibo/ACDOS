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

The backend runs on Azure App Service (Azure for Students) as one container: Linux, plan B1,
**Spain Central**, one uvicorn process with a solver pool of 2, Always On, health check on
`/health`, HTTPS only (#148). Cost: about $13 a month for B1 ($0.018 an hour), from the student
credit.

- **Region.** The Azure for Students subscription only allows Poland Central, India South
  Central, Switzerland North, UAE North and Spain Central. Spain Central is one of the closest
  to Supabase (eu-west-1, Ireland), which matters because each request makes several database
  round trips.
- **Image.** Student subscriptions cannot use Azure Container Registry's build service (ACR
  Tasks), so GitHub Actions builds the image (`.github/workflows/image.yml`) and pushes it to
  GHCR as a public package: `ghcr.io/ethanbwibo/acdos-api:<commit sha>`, and `:latest`. The repo
  is public and the image holds no secrets (`.dockerignore` lets in only the requirements,
  `backend/app` and `data/`; the workflow checks for env files and keys), so App Service pulls
  it anonymously. The workflow runs on every push to `main` that touches the backend, and can
  be run by hand (Actions, image, Run workflow).
- **RF fingerprint.** The image trains the Random Forest at build time. The workflow prints its
  fingerprint and fails unless it equals `RF_FINGERPRINT` in the workflow, which is what
  `cd backend && python -m app.ml.fingerprint` prints locally.
- **Deploy by SHA**, never by `latest`, so the app runs exactly the image whose fingerprint was
  checked.

Run these in Git Bash, signed in with `az login`:

```bash
RG=acdos-rg LOC=spaincentral PLAN=acdos-plan APP=acdos-api
IMAGE=ghcr.io/ethanbwibo/acdos-api SHA=<full commit sha the image workflow pushed>

# Once: the resource group, the plan and the app.
az group create -n $RG -l $LOC
az appservice plan create -g $RG -n $PLAN --is-linux --sku B1 -l $LOC
az webapp create -g $RG -p $PLAN -n $APP --container-image-name $IMAGE:$SHA
az webapp config set -g $RG -n $APP --always-on true   --generic-configurations '{"healthCheckPath": "/health"}'
az webapp update -g $RG -n $APP --https-only true
az webapp config appsettings set -g $RG -n $APP --settings WEBSITES_PORT=8000 SOLVER_POOL_SIZE=2
```

`DATABASE_URL` is set by hand and never committed. Copy it from the Supabase dashboard:
Connect, **Session pooler** (port 5432), as `postgres`, with the password filled in. It must
look like `postgresql://postgres.<ref>:<password>@aws-….pooler.supabase.com:5432/postgres`.

**Don't pass it on the command line** (`az … --settings DATABASE_URL='…'`). On Windows, `az` is
`az.cmd`, so `cmd.exe` parses the arguments again, from Git Bash or PowerShell alike. Characters
such as `&`, `%`, `^`, `!` or quotes in the URL or password then cut or garble the value.
`az` reports success anyway. The app then exits at startup with
`invalid DSN: scheme is expected to be either "postgresql" or "postgres"`, and `/health`
returns 503. Use one of these instead:

- **Azure Portal (simplest).** App Services, `acdos-api`, Settings, **Environment variables**.
  Add or edit `DATABASE_URL`, paste the URL as the value, then Apply, Apply and Confirm. The
  app restarts by itself.
- **A JSON file**, so no shell parses the URL. In PowerShell:

  ```powershell
  notepad $env:TEMP\dburl.json
  #   contents: [{"name":"DATABASE_URL","value":"postgresql://...","slotSetting":false}]
  az webapp config appsettings set -g acdos-rg -n acdos-api --output none --settings "@$env:TEMP\dburl.json"
  Remove-Item $env:TEMP\dburl.json
  ```

  Keep `--output none`: without it, `az` prints every setting back, the URL included.

Then check the app started. Download the logs and look for `Application startup complete`
in the newest `*_default_docker.log` under `LogFiles/`:

```bash
az webapp log config -g $RG -n $APP --docker-container-logging filesystem   # once
az webapp log download -g $RG -n $APP --log-file logs.zip
```

Redeploy after a change: merge to `main`, wait for the image workflow to pass (it pushes
`$IMAGE:<sha>`), then point the app at that SHA and check it:

```bash
az webapp config container set -g $RG -n $APP --container-image-name $IMAGE:$SHA
curl https://$(az webapp show -g $RG -n $APP --query defaultHostName -o tsv)/health
```

The app's HTTPS address goes in `android-client/local.properties` as `api.baseUrl=https://...`.

### After the defence

Stopping the app (`az webapp stop`) does **not** stop the bill: the B1 plan charges whether
the app runs or not. To stop all charges, delete the resource group, which deletes the app
and the plan together (Supabase is not in it):

```bash
az group delete -n acdos-rg --yes
```

The GHCR images cost nothing; delete them in the repo's Packages page if wanted.

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
