# Demo runbook

The defence demo, start to finish: one morning of crew pickups, planned, driven, disrupted
by a breakdown and re-planned, then acknowledged by the crew member and answered with a preset
message. It takes two devices, with the app built against the Azure URL
(`api.baseUrl=https://acdos-api.azurewebsites.net` in `android-client/local.properties`):
the dispatcher on the laptop's emulator, and one phone that is the driver first and the crew
member at the end.

| Device | Account | Shows |
|---|---|---|
| Emulator (`Dispatcher_API34`) | `dispatcher@acdos.test` | Crew messages, Routes, Pickups and Vehicles for a day; plans and re-plans |
| Phone, steps 5–7 | `driver@acdos.test` | its van's route, stop by stop |
| Phone, steps 8–9 | `crew@acdos.test` | Pickup: its next pickup and any change to acknowledge. Message: the presets |

Close Android Studio before starting the emulator: the laptop does not have the memory for
both. Start it from PowerShell:
`& "$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe" -avd Dispatcher_API34 -gpu host -no-boot-anim`.

The password for all three is `SEED_PASSWORD` (`scripts/seed_test_accounts.py`).

## The day before

1. `https://acdos-api.azurewebsites.net/health` returns `{"status":"ok"}`. If it doesn't, see
   README, "Deploy", or use the fallback below.
2. The accounts exist: `python scripts/seed_test_accounts.py` (safe to re-run).
3. Sign in once with each account (dispatcher on the emulator; driver, then crew, on the
   phone) and check that it loads. Leave the phone signed in as the driver.

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
3. **Dispatcher plans** (dispatcher): tap **Next** to tomorrow. Pickups shows 14 pending.
   Tap **Run optimisation**, **untick the test vans `KDA 001T` and `KDA 002T`** so only the
   three `demo-` vans are selected, and start the job. A plan that includes a test van can't
   be removed by `reset` later. When the job finishes, Routes shows the demo vans' routes,
   with stops, times and crew names.
4. **Find the crew member's van** (dispatcher): in Routes, note the van whose route lists
   "Test Crew". That is the van to break down in step 6.
5. **Driver confirms** (phone, as the driver): refresh. The route for `demo-KDH 101A` appears. Tap
   **Picked up** on the first stop. After **Refresh**, the dispatcher's Pickups shows it
   `picked_up`.
6. **Breakdown** (dispatcher): in Vehicles, **Mark broken down** the van carrying
   Test Crew. The banner says it is broken down and asks for a re-plan.
7. **Re-plan** (dispatcher): tap **Re-plan**. The broken van's uncollected pickups move
   to the other vans. Crew already on board stay where they are. Routes shows the new plan.
   If the broken van was `demo-KDH 101A`, the driver phone shows the shortened route, or
   "No route assigned", on refresh.
8. **Crew acknowledges** (phone): **Sign out**, then sign in as `crew@acdos.test`. The
   Pickup tab opens with a card on top, "Your pickup has changed": the reason (Vehicle
   breakdown), the new pickup time with the old one, and the new van. Below it, the pickup
   time, "Report at JKIA 06:15" and the van. Tap **Acknowledge**: "Acknowledged. The
   dispatcher can see it." and the card goes. It stays gone after a pull to refresh.
9. **Crew messages the dispatcher** (phone, then dispatcher): open the **Message** tab. It
   lists the presets as buttons and has no text field. Tap **I am running late**: "Sent to
   the dispatcher." On the emulator, tap **Refresh**: Crew messages, at the top, shows
   "Test Crew: I am running late" with the time it was sent.

**After the demo:** run `reset`. On the phone, sign out and sign back in as the driver. To
run the demo again, start from step 1.

## If something goes wrong

- **The seed prints `non-demo pending pickup(s)`.** Another script (for example
  `plan_test_route.py`) has pickups on the same day. Seed another day with
  `seed --date YYYY-MM-DD` and tap Next to that day on the dispatcher phone.
- **Reset says a job mixed demo and non-demo rows.** A plan included a non-demo van or pickup.
  Nothing was deleted. Remove that job's routes by hand, or leave it and seed another day.
- **No change card in step 8.** The re-plan didn't move Test Crew's pickup time, or the
  notice was acknowledged on an earlier run. Pull to refresh; if it still doesn't show, the
  rest of the demo still works, and the Message tab does not depend on it.
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
`android-client/local.properties`, rebuild, and install on the emulator and the phone. The demo steps are
the same. The database is the same Supabase project, so the seeded rows are already there.
Keep the laptop awake and on power.
