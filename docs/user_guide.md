# ACDOS user guide

ACDOS gets Kenya Airways crew from home to JKIA before their report time. There is one app, and it shows each person the screens for their role:

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
5. **Sign out** and **Theme** (System, Light or Dark):
   - **Drivers and crew:** open the menu at the top right, then **Profile**. Both are at the bottom of that screen.
   - **Dispatcher:** both are in the menu at the top right.

---

## Dispatcher

Five tabs: **Overview**, **Plan**, **Routes**, **Fleet & crew** and **Messages**. A screen opened from a tab (a route, Re-plan, Import roster) opens inside that tab, with a back arrow; the tabs stay at the bottom. Each tab stays where you left it. Tap the tab you're on to go back to its first screen. **Messages** shows the number of unread messages on its tab.

### Overview

- **The day:** **Previous** and **Next** move between days. The title shows the date. Every tab shows this day.
- **The tiles:**
  - **crew pickups:** how many crew need transport that day.
  - **vehicles:** how many vans there are.
  - **late risk:** crew the plan expects to be late.
- **Plan:** the state of the day's plan: Not planned, Running or Planned. Once it's planned, it also shows the drive time, the vans used and whether all crew are on time.
- **Alerts:** broken-down vans, flight delays waiting for a re-plan (tap to open Re-plan on the Plan tab), and unread crew messages (tap to open Messages).
- **Refresh** reloads the day. A banner says if there's no connection; the screen may then be out of date, and changes can't be sent.

### Plan a day

1. On **Overview**, go to the day with **Next**, and check that the **crew pickups** count is right. **Fleet & crew > Pickups** lists each pickup and its status.
2. Open the **Plan** tab. It shows the report window and the vans available.
3. Tap **Start**. Under **Vans to plan with**, only vans that can be planned are listed and ticked:
   - not broken down or unavailable;
   - not already on the road.

   Untick any van you want to keep back, then tap **Start**.
4. **Job status** goes from Queued to Running to Done, usually in a few seconds. "Plan ready" gives the number of routes, late crew and unassigned crew.
5. Open the **Routes** tab. It now lists each van's route. Tap one to see its stops, with:
   - the pickup times;
   - each crew member's report time;
   - the van's arrival at JKIA and the slack before the first report time.

**Times come from the travel-time model,** which knows Nairobi's traffic by hour and day.

### Import a roster

1. Open **Fleet & crew > Pickups** and tap **Import roster**, then pick the CSV file. The format is in `docs/roster_import.md`.
2. The app checks the file first and imports nothing yet. It shows:
   - how many rows, new crew and pickups the file would add;
   - **Pickup points:** for each row that gives a pickup location, the nearest pickup zone and how far the point is from it. A point far from its zone, or in the wrong zone, is usually a typo, or latitude and longitude swapped. Fix the file and choose it again;
   - **Rows skipped,** each with the reason.
3. Tap **Import N pickups** to import. Rows with no pickup location are collected from the crew member's home. A new crew member needs a location on at least one row.

**Moving a crew member's home:** put the new point in their row and `yes` in its `set_home` column. The check shows it under **Home moves**, e.g. "Home moves: Kilimani → Kasarani (14.1 km)", before anything changes. Without `yes`, a point is for that one pickup only, e.g. a hotel. A crew member's "I need to change my pickup address" message is the usual reason for one.

**Pickup locations come from Google Maps:** right-click the spot on a computer, click the coordinates to copy them, and paste them into the cell. A full Google Maps link works too; a short `maps.app.goo.gl` link doesn't. The steps are in `docs/roster_import.md`, "Getting a pickup point from Google Maps".

### A van breaks down

1. Open **Fleet & crew > Vehicles**, tap the van, then **Mark broken down**.
2. **Overview**'s Alerts and the top of the **Plan** tab show the van as broken down. Tap either: Re-plan opens on the Plan tab.
3. The screen shows what will be re-planned:
   - **Fixed (already departed):** routes that have left. These are never changed, except the broken van's.
   - **Re-solved:** pickups that will be planned again.
4. Tap **Re-plan**, then **Start**. When it's done, **Before** and **After** compare the old and new plans: minutes, vans and late crew.
5. **Crew whose pickup changed** see a "Pickup changed" card in their app. The crew pickups list says **Awaiting acknowledgement** (for example "Planned · Awaiting acknowledgement") until they acknowledge it, then **Acknowledged**. If the crew member is picked up or missed first, the flag goes: their app no longer shows that pickup, so there is nothing left to acknowledge.
6. **When the van is fixed,** open it and tap **Mark available**.

### A flight is delayed

1. Open **Fleet & crew > Pickups** and tap that crew member's pickup. Only a pickup that is Not planned or Planned can change.
2. Tap **Flight delay: change report time** and pick the new time, on the same day.
3. Overview and the Plan tab show "Flight delay for …" with **Re-plan ›**. Tap it, then **Re-plan** and **Start**, as for a breakdown. The crew member gets a "Pickup changed" card.

**Messages never re-plan anything by themselves.** Re-planning is always your decision.

### Crew messages

1. The **Messages** tab shows the number of unread messages. Open it to see them, with **All** or **Unread**.
2. **Tap a message:** it's marked read (only while the Messages tab is on screen), and the reply presets appear under it:
   - **Noted**
   - **Van rerouted**
   - **Call the dispatcher**
3. **Tap a reply:** "Reply sent." The message's row then says "Replied: …".
4. **Replies are presets only.** Each goes only to that crew member. There is no free text and no chat between crew and drivers.

---

## Driver

Three tabs: **Route**, **Schedule** and **Sync**.

### Route

1. **What it shows:** your van's route for now, on a map ending at JKIA, with a chip saying how many are picked up (for example "1 of 4 picked up").
   - **Next pickup:** the area and the crew member's name, then:
     - **Pickup by:** the time to pick them up;
     - **From previous stop:** about how many minutes' drive;
     - **Arrive JKIA by:** when the van is planned to reach JKIA. This is one time for the whole route, not each crew member's report time.
   - **Then:** the stops after it, in order. Each row has the area, the crew member's name, the minutes from the previous stop and the pickup time.
   - **No-shows:** crew recorded as not at the pickup point, so you can still record them if they turn up (tap the row, see step 3).
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

### Profile

Open the menu at the top right, then **Profile**. It shows your name, your van's plate, its seats and its status, as the dispatcher has them. It works without signal, showing what it last loaded. Nothing here can be changed. If your van is wrong, ask the dispatcher.

## Crew

Two tabs: **Pickup** and **Message**.

### Pickup

1. **My pickup** shows your next pickup:
   - the pickup time;
   - **Report at JKIA:** your report time;
   - the **Vehicle**.

   "Time not set yet" or "Not assigned yet" means the dispatcher hasn't planned it yet.
   **"No pickup to come. If you've been picked up, you're on your way."** means you have
   nothing still to be collected, including once the driver has picked you up. It does not
   mean your pickup was cancelled.
2. **If your pickup changes,** a **Pickup changed** card shows at the top. It gives:
   - the old and new pickup times;
   - the reason: a flight delay, a vehicle breakdown or a route re-plan.
3. **Tap Acknowledge:** "Acknowledged. The dispatcher can see it." The card goes.
4. **Pull down to refresh.** Without signal, the screen shows what it last loaded and says so.

### Message

1. Pick one of the messages:
   - **I am running late**
   - **I am at the pickup point**
   - **I cannot find the van**
   - **My flight has changed**
   - **Please call me**
   - **I need to change my pickup address**

   It goes to the dispatcher only: "Sent to the dispatcher." You can't type free text.
2. **Recent** lists what you sent. "Seen" means the dispatcher has read it, and their reply shows under it as "Dispatch · …". Pull down to check for a reply.
3. **No signal?** "Not sent: no connection. Tap it again to retry."
4. **Moving house?** Send **I need to change my pickup address**. The app never changes your address itself: the dispatcher gives your pickups the new address in the next roster import. Pickups already planned keep the old one.

### Profile

Open the menu at the top right, then **Profile**. It shows your name, your crew role, your home zone (the pickup area nearest your home), and your next pickup's time and status. It works without signal, showing what it last loaded.

Nothing here can be changed. Your home address comes from the roster, and journey times are worked out per pickup zone, so a pin you set yourself could give a wrong time. To change your address, send **I need to change my pickup address** from the Message tab.
