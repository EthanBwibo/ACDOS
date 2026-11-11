# ACDOS user guide

**Draft for #41.** ACDOS gets Kenya Airways crew from home to JKIA before their report time. There is one app, and it shows each person the screens for their role:

| Role | What they do |
|---|---|
| **Dispatcher** | Plans the vans, handles breakdowns and delays, and answers crew messages |
| **Driver** | Follows the van's route and records each pickup |
| **Crew** | Checks their pickup, acknowledges changes, and messages the dispatcher |

## Signing in (everyone)

1. Open **ACDOS** and enter your **Work email** and **Password**. Tap **Sign in**.
2. The app opens your role's screens. You never choose a role: it comes from your account.
3. **If something goes wrong:**
   - **"Wrong email or password."** Check both and try again.
   - **"No connection to the server."** Check your signal and try again.
   - **"This account is not set up yet."** Your account has no role yet. Ask the dispatcher.
   - **"Your account's role has changed. Sign in again."** Your role was changed while you were signed in. Sign in again to get the right screens.
   - **Forgot password?** Accounts are managed by the dispatcher; ask them to reset it.
4. **Once you've signed in, the app opens without signal,** using what it last loaded.
5. **Sign out** and **Theme** (System, Light or Dark) are in the menu at the top right.

---

## Dispatcher

The dispatcher screen is a **hub** for one day. Tap a tile or link to open the detail, and **Back** to return. There is no tab bar.

### The hub

- **The day:** **Previous** and **Next** move between days. The title shows the date.
- **The tiles:**
  - **crew pickups:** how many crew need transport that day.
  - **vehicles:** how many vans there are.
  - **late risk:** crew the plan expects to be late.
- **Plan:** the state of the day's plan: Not planned, Running or Planned. Once it's planned, it also shows the drive time, the vans used and whether all crew are on time.
- **Alerts:** broken-down vans and unread crew messages.
- **Routes:** each planned van, with its crew count.
- **Refresh** reloads the day. A banner says if there's no connection; the screen may then be out of date, and changes can't be sent.

### Plan a day

1. Go to the day with **Next**, and check that the **crew pickups** count is right. Tap the tile to see each pickup and its status.
2. Tap **Run optimisation**. The screen shows the report window and the vans available.
3. Tap **Start**. Under **Vans to plan with**, only vans that can be planned are listed and ticked:
   - not broken down or unavailable;
   - not already on the road.

   Untick any van you want to keep back, then tap **Start**.
4. **Job status** goes from Queued to Running to Done, usually within a minute. "Plan ready" gives the number of routes, late crew and unassigned crew.
5. Go **Back**. **Routes** now lists each van's route. Tap one to see its stops, with:
   - the pickup times;
   - each crew member's report time;
   - the van's arrival at JKIA and the slack before the first report time.

**Times come from the travel-time model,** which knows Nairobi's traffic by hour and day.

### A van breaks down

1. Tap the **vehicles** tile, then the van, then **Mark broken down**.
2. Back on the hub, **Alerts** shows the van as broken down. Tap the alert.
3. The screen shows what will be re-planned:
   - **Fixed (already departed):** routes that have left. These are never changed, except the broken van's.
   - **Re-solved:** pickups that will be planned again.
4. Tap **Re-plan**, then **Start**. When it's done, **Before** and **After** compare the old and new plans: minutes, vans and late crew.
5. **Crew whose pickup changed** see a "Pickup changed" card in their app. The crew pickups list says **Awaiting acknowledgement** (for example "Planned · Awaiting acknowledgement") until they acknowledge it, then **Acknowledged**. If the crew member is picked up or missed first, the flag goes: their app no longer shows that pickup, so there is nothing left to acknowledge.
6. **When the van is fixed,** open it and tap **Mark available**.

### A flight is delayed

1. Open the crew pickups list and tap that crew member's pickup. Only a pickup that is Not planned or Planned can change.
2. Tap **Flight delay: change report time** and pick the new time, on the same day.
3. The hub shows "Flight delay for …" with **Re-plan ›**. Tap it, then **Re-plan** and **Start**, as for a breakdown. The crew member gets a "Pickup changed" card.

**Messages never re-plan anything by themselves.** Re-planning is always your decision.

### Crew messages

1. **Alerts** counts unread messages. Tap **Messages** to see them, with **All** or **Unread**.
2. **Tap a message:** it's marked read, and the reply presets appear under it:
   - **Noted**
   - **Van rerouted**
   - **Call the dispatcher**
3. **Tap a reply:** "Reply sent." The message's row then says "Replied: …".
4. **Replies are presets only.** Each goes only to that crew member. There is no free text and no chat between crew and drivers.

---

## Driver

Three tabs: **Route**, **Schedule** and **Sync**.

### Route

1. **What it shows:** your van's route for now: the **Next pickup**, then the stops after it, ending at JKIA. Each stop has:
   - the crew member's name and area;
   - **Pickup by:** the time to pick them up;
   - **Arrive JKIA by:** their report time.

   The progress line says how many are picked up.
2. **Navigate** opens your maps app at the next stop.
3. At the stop, tap **Confirm pickup**. It shows the **Scheduled pickup** time and **Now**:
   - **Crew on board:** they're in the van.
   - **Crew not at pickup point:** records a no-show after you confirm. If they turn up later, you can still record them on board.
   - **Report a problem:** a **Vehicle issue** or a **Traffic delay**. The dispatcher sees it.
4. **Pull down to refresh** the route. Do this after the dispatcher re-plans: the app isn't told about a re-plan until it refreshes.
5. When every stop is done: "No more pickups on this route."

### Schedule

- **Today** and **Upcoming** routes, each with its crew count and start time. "In progress" marks the one you're driving.

### Sync: working without signal

- **Every tap is saved on the phone first.** "Saved on this phone first. Sends when signal returns."
- **The chip at the top** shows Online or Offline and how many events are queued.
- **The Sync tab lists the queue in order.** Each event is Queued, Sent or Not accepted. **Sync now** sends straight away.
- **Nothing is lost or sent twice,** however many times the signal drops (tested in #34).
- **"Not accepted"** means the server refused that event, for example "This pickup was already confirmed". The dispatcher's record is the correct one.

---

## Crew

Two tabs: **Pickup** and **Message**.

### Pickup

1. **My pickup** shows your next pickup:
   - the pickup time;
   - **Report at JKIA:** your report time;
   - the **Vehicle**.

   "Time not set yet" or "Not assigned yet" means the dispatcher hasn't planned it yet.
   **"No pickup coming up"** means you have nothing still to be collected. That includes
   once the driver has picked you up: it does not mean your pickup was cancelled.
2. **If your pickup changes,** a **Pickup changed** card shows at the top. It gives:
   - the old and new pickup times;
   - the reason: a flight delay, a standby activation, a vehicle breakdown or a route re-plan.
3. **Tap Acknowledge:** "Acknowledged. The dispatcher can see it." The card goes.
4. **Pull down to refresh.** Without signal, the screen shows what it last loaded and says so.

### Message

1. Pick one of the messages:
   - **I am running late**
   - **I am at the pickup point**
   - **I cannot find the van**
   - **My flight has changed**
   - **Please call me**

   It goes to the dispatcher only: "Sent to the dispatcher." You can't type free text.
2. **Recent** lists what you sent. "Seen" means the dispatcher has read it, and their reply shows under it as "Dispatch · …". Pull down to check for a reply.
3. **No signal?** "Not sent: no connection. Tap it again to retry."
