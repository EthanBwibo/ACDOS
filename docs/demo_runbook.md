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
| Phone, step 6 | `driver-101a@`, `driver-102a@` or `driver-103a@acdos.test` (the driver of a van in the new plan) | its van's route, stop by stop |
| Phone, steps 7–8 | `crew@acdos.test` | Pickup: its next pickup and any change to acknowledge. Message: the presets |

Close Android Studio before starting the emulator: the laptop does not have the memory for
both. Start it from PowerShell:
`& "$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe" -avd Dispatcher_API34 -gpu host -no-boot-anim`.

The password for every account is `SEED_PASSWORD` (`scripts/seed_test_accounts.py`).

## The day before

1. `https://acdos-api.azurewebsites.net/health` returns `{"status":"ok"}`. If it doesn't, see
   README, "Deploy", or use the fallback below.
2. The accounts exist: `python scripts/seed_test_accounts.py` (safe to re-run).
3. Sign in once with each account (dispatcher on the emulator; the three van drivers, then
   crew, on the phone) and check that it loads.

## The demo

Run the two commands from `backend/` with `DATABASE_URL` in `backend/.env`.

1. **Reset** (laptop): `python -m benchmarks.demo_seed reset`. It deletes the previous run's
   demo rows (vans and crew named `demo-…`) and everything planned from them. It never touches
   the test accounts or other rows.
2. **Seed** (laptop): `python -m benchmarks.demo_seed seed`. This creates tomorrow's morning
   (Nairobi time): 3 vans of 14 seats, `demo-KDH 101A`, `demo-KDH 102A` and `demo-KDH 103A`,
   driven by `driver-101a@`, `driver-102a@` and `driver-103a@acdos.test`, plus 14 pending
   pickups across Westlands, Kilimani, Lavington, Karen, South C, Embakasi and Kasarani,
   reporting at JKIA 05:00 to 07:30.
   One of them is `crew@acdos.test`'s (Westlands, 06:15). If it stops with
   `missing test account(s): …`, run `python scripts/seed_test_accounts.py` and seed again.
   **Read the warnings it prints.** The test vans `KDA 001T` and `KDA 002T` (fixtures of
   `plan_test_route.py`) stay in the database, so it may list them; step 3 leaves them out.
3. **Dispatcher plans** (dispatcher): tap **Next** to tomorrow. Pickups shows 14 pending.
   Tap **Run optimisation**, **untick the test vans `KDA 001T` and `KDA 002T`** so only the
   three `demo-` vans are selected, and start the job. A plan that includes a test van can't
   be removed by `reset` later. When the job finishes, Routes shows the demo vans' routes,
   with stops, times and crew names.
4. **Breakdown** (dispatcher), before anyone is picked up: in Routes, find the van whose
   route lists "Test Crew". In Vehicles, **Mark broken down** that van. The banner says it is
   broken down and asks for a re-plan.
5. **Re-plan** (dispatcher): tap **Re-plan**, untick the test vans again as in step 3, and
   start the job. The broken van's pickups move to the other demo vans, and Routes shows the
   new plan. Nobody has been picked up yet, so every pickup on the
   broken van is re-planned. In Pickups, Test Crew's row now says "Awaiting acknowledgement".
6. **Driver confirms** (phone): sign in as the driver of one of the vans in the new plan
   (`demo-KDH 10xA` → `driver-10xa@acdos.test`). After the breakdown re-plan, pull down on
   the Route tab to refresh: the app isn't told about a re-plan, so a driver already signed
   in can show the old route until then. That van's re-planned route appears. Tap **Confirm
   pickup**, then **Crew on board**. After **Refresh**, the
   dispatcher's Pickups shows it `picked_up`.
7. **Crew acknowledges** (phone): **Sign out**, then sign in as `crew@acdos.test`. The
   Pickup tab opens with a card on top, "Pickup changed": the old pickup time, the new one,
   and the reason (a vehicle breakdown). Below it are the pickup time, "Report at JKIA" 06:15
   and the new van. Tap **Acknowledge**: "Acknowledged. The
   dispatcher can see it." The card goes, and it stays gone after a pull to refresh. On the
   emulator, tap **Refresh**: Test Crew's row in Pickups now says "Acknowledged".
8. **Crew messages the dispatcher** (phone, then dispatcher): open the **Message** tab. It
   lists the presets as buttons and has no text field. Tap **I am running late**: "Sent to
   the dispatcher.", and it appears under **Recent**. On the emulator, tap **Refresh**: Crew
   messages, at the top, shows
   "Test Crew: I am running late" with the time it was sent.

**After the demo:** run `reset`. To run the demo again, start from step 1 (the phone signs
in as that run's driver in step 6).

## If something goes wrong

- **The seed prints `non-demo pending pickup(s)`.** Another script (for example
  `plan_test_route.py`) has pickups on the same day. Seed another day with
  `seed --date YYYY-MM-DD` and tap Next to that day on the dispatcher phone.
- **Reset says a job mixed demo and non-demo rows.** A plan included a non-demo van or pickup.
  Nothing was deleted. Remove that job's routes by hand, or leave it and seed another day.
- **No change card in step 7.** The re-plan didn't move Test Crew's pickup time or van
  (check that step 4 broke her van), or the notice was acknowledged on an earlier run. Pull
  to refresh; if it still doesn't show, the rest of the demo still works, and the Message
  tab does not depend on it.
- **The driver phone shows no route.** It is signed in as a driver whose van has no stops
  in the new plan (the broken van's driver, for example). Check Routes on the dispatcher and
  sign in as the driver of a van listed there.

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
