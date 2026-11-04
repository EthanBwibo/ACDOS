# Demo runbook

The defence demo, start to finish: one morning of crew pickups, planned, driven, disrupted
by a breakdown and re-planned. It takes three phones (or emulators), each signed in to one
test account, with the app built against the Azure URL
(`api.baseUrl=https://acdos-api.azurewebsites.net` in `android-client/local.properties`).

| Phone | Account | Shows |
|---|---|---|
| Dispatcher | `dispatcher@acdos.test` | Pickups, Vehicles and Routes for a day; plans and re-plans |
| Driver | `driver@acdos.test` | its van's route, stop by stop |
| Crew | `crew@acdos.test` | its next pickup: time, van, report time |

The password for all three is `SEED_PASSWORD` (`scripts/seed_test_accounts.py`).

## The day before

1. `https://acdos-api.azurewebsites.net/health` returns `{"status":"ok"}`. If it doesn't, see
   README, "Deploy", or use the fallback below.
2. The accounts exist: `python scripts/seed_test_accounts.py` (safe to re-run).
3. Sign in on each phone once and check that it loads.

## The demo

Run the two commands from `backend/` with `DATABASE_URL` in `backend/.env`.

1. **Reset** (laptop): `python -m benchmarks.demo_seed reset`. It deletes the previous run's
   demo rows (vans and crew named `demo-…`) and everything planned from them. It never touches
   the three accounts or other rows.
2. **Seed** (laptop): `python -m benchmarks.demo_seed seed`. This creates tomorrow's morning
   (Nairobi time): 3 vans of 14 seats, `demo-KDH 101A` (driven by `driver@acdos.test`),
   `demo-KDH 102A` and `demo-KDH 103A`, plus 14 pending pickups across Westlands, Kilimani,
   Lavington, Karen, South C, Embakasi and Kasarani, reporting at JKIA 05:00 to 07:30.
   One of them is `crew@acdos.test`'s (Westlands, 06:15).
   **Read the warnings it prints.** The test vans `KDA 001T` and `KDA 002T` (fixtures of
   `plan_test_route.py`) stay in the database, so it may list them; step 3 leaves them out.
3. **Dispatcher plans** (dispatcher phone): tap **Next** to tomorrow. Pickups shows 14
   pending. Tap **Run optimisation**, **untick the test vans `KDA 001T` and `KDA 002T`** so
   only the three `demo-` vans are selected, and start the job. A plan that includes a test
   van can't be removed by `reset` later. When the job finishes, Routes shows the demo vans'
   routes, with stops, times and crew names.
4. **Crew sees the pickup** (crew phone): refresh. It shows the pickup time, the van and
   "Report at JKIA 06:15". Note which van it's on: it's the one whose route lists
   "Test Crew" on the dispatcher's Routes.
5. **Driver confirms** (driver phone): refresh. The route for `demo-KDH 101A` appears. Tap
   **Picked up** on the first stop. The dispatcher's Pickups shows it `picked_up`.
6. **Breakdown** (dispatcher phone): in Vehicles, **Mark broken down** the van carrying
   Test Crew. The banner says it is broken down and asks for a re-plan.
7. **Re-plan** (dispatcher phone): tap **Re-plan**. The broken van's uncollected pickups move
   to the other vans. Crew already on board stay where they are. Routes shows the new plan.
   If the broken van was `demo-KDH 101A`, the driver phone shows the shortened route, or
   "No route assigned", on refresh.
8. **Crew acknowledges** (crew phone): refresh. It shows the new pickup time and van. The app
   has no Acknowledge button yet, so acknowledge from the laptop with the crew's token from
   `python scripts/seed_test_accounts.py --tokens`. In PowerShell:

   ```powershell
   $api = "https://acdos-api.azurewebsites.net"; $h = @{ Authorization = "Bearer <crew token>" }
   $p = Invoke-RestMethod "$api/crew/me/pickup" -Headers $h; $p | ConvertTo-Json -Depth 5
   Invoke-RestMethod -Method Post "$api/crew/me/notices/<notice id from above>/acknowledge" -Headers $h
   ```

   After a refresh, the notice is gone from the crew's pickup.

**After the demo:** run `reset`. To run the demo again, start from step 1.

## If something goes wrong

- **The seed prints `non-demo pending pickup(s)`.** Another script (for example
  `plan_test_route.py`) has pickups on the same day. Seed another day with
  `seed --date YYYY-MM-DD` and tap Next to that day on the dispatcher phone.
- **Reset says a job mixed demo and non-demo rows.** A plan included a non-demo van or pickup.
  Nothing was deleted. Remove that job's routes by hand, or leave it and seed another day.
- **The driver phone shows another route.** `driver@acdos.test` also drives `KDA 001T`.
  The phone shows the active route that starts first. `python scripts/plan_test_route.py
  --complete` clears the test routes.

## Fallback: Azure is down

Run the backend on the laptop and expose it with a Cloudflare quick tunnel (README, "Deploy").
This needs no account, but the address changes every run, so every phone needs a rebuilt app.
Allow about 15 minutes, and start it before the defence, not during it.

```bash
cd backend && venv\Scripts\activate      # DATABASE_URL in backend/.env
uvicorn app.main:app --workers 1 --port 8000
cloudflared tunnel --url http://localhost:8000      # second terminal; keep both open
```

Check `https://<words>.trycloudflare.com/health`, then set `api.baseUrl` to that address in
`android-client/local.properties`, rebuild, and install on the three phones. The demo steps are
the same. The database is the same Supabase project, so the seeded rows are already there.
Keep the laptop awake and on power.
