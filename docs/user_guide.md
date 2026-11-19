# ACDOS user guide

ACDOS gets Kenya Airways crew from home to JKIA before their report time. There is one app, and it shows each person the screens for their role:

| Role | What they do |
|---|---|
| **Dispatcher** | Gets the day's pickups in, plans the vans wave by wave, handles breakdowns and delays, and answers crew messages |
| **Driver** | Follows the van's route, records each pickup, and can call the crew member around the pickup |
| **Crew** | Checks their pickup, acknowledges changes, messages the dispatcher, and can call the driver around the pickup |

**The app doesn't send notifications.** Push notifications aren't built. A change shows when
the app refreshes: when you open the screen, or pull down on it. If you're expecting a change,
pull down to check.

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
   - **Everyone:** open the menu at the top right, then **Profile**. Both are at the bottom of that screen.

---

## Dispatcher

Five tabs: **Overview**, **Plan**, **Routes**, **Fleet & crew** and **Messages**. A screen opened from a tab (a route, Re-plan, Import roster, Add pickup, a crew member) opens inside that tab, with a back arrow; the tabs stay at the bottom. Each tab stays where you left it. Tap the tab you're on to go back to its first screen. **Messages** shows the number of unread messages on its tab.

### Overview

- **The day:** **Previous** and **Next** move between days. The title shows the date. Every tab shows this day.
- **The tiles:** tap one to open its list in **Fleet & crew**.
  - **crew pickups:** how many crew need transport that day.
  - **vehicles:** how many vans there are.
  - **late risk:** crew the plan expects to be late.
- **Plan:** the state of the day's plan: Not planned, Running or Planned. Once it's planned, it also shows the drive time, the vans used and whether all crew are on time.
- **Alerts:** broken-down vans, a broken-down van's later route that needs a van (for example "KDX 004's 08:00–10:00 route needs a van"), flight delays waiting for a re-plan (tap any of these to open Re-plan on the Plan tab), and unread crew messages (tap to open Messages).
- **Refresh** reloads the day. A banner says if there's no connection; the screen may then be out of date, and changes can't be sent.

### Plan a day, wave by wave

A day is planned one **wave** at a time: crew whose report times are close together. The app
groups the day's unplanned pickups for you. A gap of more than an hour between report times,
or a wave reaching 4 hours, starts a new wave. One plan can't cover more than 4 hours of
report times; the server refuses it ("these pickups' report times span …, more than the 4 h
one plan may cover: plan each wave separately").

1. On **Overview**, go to the day with **Next**, and check that the **crew pickups** count is right. **Fleet & crew > Pickups** lists each pickup and its status.
2. Open the **Plan** tab. Under **Waves**, each wave is a chip, for example "04:00–06:30 · 42 crew". Tap **Next wave** to select the earliest one not yet planned, or tap a chip. Start stays off until a wave is selected.
3. Tap **Start**. Under **Vans to plan with**, each van says what it can do for this wave:
   - **plate only:** free, from the depot. Ticked.
   - **"Free from 07:15":** its earlier route is due back at JKIA in time, so it starts from JKIA then. Ticked.
   - **"On wave 04:00–06:30":** it already has a route in this wave. Unticked; tick it to re-plan that route with this wave.
   - **"Later route 08:15":** it has a route after this wave. Unticked; if you tick it, it's left out (step 4).

   Broken-down or unavailable vans aren't listed. Untick any van you want to keep back, then tap **Start**.
4. **Job status** goes from Queued to Running to Done, usually within half a minute. "Plan ready" gives the number of routes, late crew and unassigned crew. A van that was left out because of a later route is listed, for example "KDX 004 left out: has the 08:00–10:00 route".
5. Open the **Routes** tab. It now lists each van's route. Tap one to see its stops, with:
   - the pickup times;
   - each crew member's report time;
   - the van's arrival at JKIA and the slack before the first report time.
6. Plan the next wave the same way, **in order, earliest first.** The same vans can do several waves in a day.

**Times come from the travel-time model,** which knows Nairobi's traffic by hour and day.

### Import a roster

1. Open **Fleet & crew > Pickups** and tap **Import roster**, then pick the CSV file. The format is in `docs/roster_import.md`. **Download template** saves an empty roster with the right columns and two example rows. Column names can be in any case, with spaces, `-` or `_`.
2. The app checks the file first and imports nothing yet. It shows:
   - how many rows, new crew and pickups the file would add;
   - **Pickup points:** for each row that gives a pickup location, the nearest pickup zone and how far the point is from it. A point far from its zone, or in the wrong zone, is usually a typo, or latitude and longitude swapped. Fix the file and choose it again;
   - **Rows skipped,** each with the reason.
3. Tap **Import N pickups** to import. Rows with no pickup location are collected from the crew member's home. A new crew member needs a location on at least one row.

**Moving a crew member's home:** put the new point on their first pickup from the new address, with `yes` in its `set_home` column. The move counts from that pickup's report time: their earlier pickups still go to the old home, and later ones to the new. The check shows both before anything changes:
- under **Home moves**, e.g. "Home moves: Kilimani → Kasarani (14.1 km, from Fri 20 Nov)";
- under **Pickup points**, which home each row with no point uses, e.g. "home (Kilimani)" or "home (Kasarani, from Fri 20 Nov)".

Without `yes`, a point is for that one pickup only, e.g. a hotel. A crew member's "I need to change my pickup address" message is the usual reason for a move.

**Pickup locations come from Google Maps:** right-click the spot on a computer, click the coordinates to copy them, and paste them into the cell. A full Google Maps link works too; a short `maps.app.goo.gl` link doesn't. The steps are in `docs/roster_import.md`, "Getting a pickup point from Google Maps".

### Add one pickup

For a pickup that isn't on the roster, such as a standby call-out:

1. Open **Fleet & crew > Pickups** and tap **Add pickup**.
2. **Crew member:** type a name or staff number and pick them from the list.
3. **Report time (Nairobi):** tap **Pick date and time**.
4. **Type:** **Rostered** or **Standby**.
5. **Pickup location:** **Home** (it shows their home zone), or **Different location**, which opens a map. Tap the map to drop a pin: the app shows the nearest zone and how far the pin is from it. A pin more than 10 km from every zone can't be used. Tap **Use this point**.
6. Tap **Add pickup**: "Pickup added". The same checks as the roster import apply: the report time can't have passed, the point must be within the pickup zones, and the same pickup can't be added twice.

Adding a pickup doesn't plan it. Plan its wave on the Plan tab.

### Crew and their homes

**Fleet & crew > Crew** lists every crew member, 20 at a time (**Load more** for the next). Search by name or staff number. Tap a crew member to see their staff number and home zone.

**Set home** moves their home: drop a pin on the map, check the nearest zone, and tap **Save home**: "Amina's home is now in Kilimani". Pickups already added keep the old point. A crew member's "I need to change my pickup address" message is the usual reason.

### A van breaks down

1. Open **Fleet & crew > Vehicles**, tap the van, then **Mark broken down**.
2. **Overview**'s Alerts and the top of the **Plan** tab show the van as broken down. Tap either: Re-plan opens on the Plan tab.
3. The screen shows what will be re-planned:
   - **Fixed (already departed):** routes that have left. These are never changed, except the broken van's.
   - **Re-solved:** the pickups on the broken van's route in progress or next. If the van also had routes in later waves, each one shows as "KDX 004's 08:00–10:00 route needs a van", here and in Overview's alerts. Re-plan each from its alert, one at a time.
4. Tap **Re-plan**, then **Start**. When it's done, **Before** and **After** compare the old and new plans: minutes, vans and late crew.
5. **Crew whose pickup changed** see a "Pickup changed" card in their app. The crew pickups list says **Awaiting acknowledgement** (for example "Planned · Awaiting acknowledgement") until they acknowledge it, then **Acknowledged**. If the crew member is picked up or missed first, the flag goes: their app no longer shows that pickup, so there is nothing left to acknowledge.
6. **When the van is fixed,** open it and tap **Mark available**.

### A flight is delayed

1. Open **Fleet & crew > Pickups** and tap that crew member's pickup. Only a pickup that is Not planned or Planned can change.
2. Tap **Flight delay: change report time** and pick the new time, on the same day.
3. Overview and the Plan tab show "Flight delay for …" with **Re-plan ›**. Tap it, then **Re-plan** and **Start**, as for a breakdown. The crew member gets a "Pickup changed" card.

**Messages never re-plan anything by themselves.** Re-planning is always your decision.

### Crew messages

1. The **Messages** tab shows the number of unread messages. It lists one row per crew member who has messaged, latest first, with their last line and an unread count. **Needs reply** shows only those still waiting for an answer.
2. **Tap a row** to open that crew member's conversation. Their newest unanswered message is selected and marked read, and the reply presets appear under it:
   - **Noted**
   - **Van rerouted**
   - **Call the dispatcher**
3. **Tap a reply:** "Reply sent." The next unanswered message from them, if any, is selected. Back returns to the list.
4. **Replies are presets only.** Each goes only to that crew member. There is no free text and no chat between crew and drivers; crew and drivers can only phone each other, around the pickup.

### Profile

Open the menu at the top right, then **Profile**. It shows the email you signed in with, **Sign out** and **Theme**.

---

## Driver

Three tabs: **Route**, **Schedule** and **Sync**.

### Route

1. **What it shows:** your van's next route with crew still to collect, on a map ending at JKIA, with a chip saying how many are picked up (for example "1 of 4 picked up"). Your van may drive several routes in a day, one per wave: once every crew member on one is picked up or marked not there, the next one shows.
   - **Next pickup:** the area and the crew member's name, then:
     - **Pickup by:** the time to pick them up;
     - **From previous stop:** about how many minutes' drive;
     - **Arrive JKIA by:** when the van is planned to reach JKIA. This is one time for the whole route, not each crew member's report time.
   - **Then:** the stops after it, in order. Each row has the area, the crew member's name, the minutes from the previous stop and the pickup time.
   - **No-shows:** crew recorded as not at the pickup point, so you can still record them if they turn up (tap the row, see step 3).
2. **Navigate** opens Google Maps with directions to the next stop, or another maps app if Google Maps isn't installed.
   **Call** (for example **Call Amina**) phones the crew member. It shows only from 30 minutes before the pickup until it's done; the number isn't kept on the phone.
3. At the stop, tap **Confirm pickup**. It shows the **Scheduled pickup** time and **Now**:
   - **Crew on board:** they're in the van.
   - **Crew not at pickup point:** records a no-show after you confirm. If they turn up later, you can still record them on board.
   - **Report a problem:** a **Vehicle issue** or a **Traffic delay**. The dispatcher sees it.
4. **Pull down to refresh** the route. Do this after the dispatcher re-plans: the app doesn't get notifications, so it shows a re-plan only when it refreshes.
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
   - the **Vehicle**;
   - the **Driver**'s first name, once the pickup is planned. **Call driver** phones them, from 30 minutes before your pickup until you're picked up.

   "Time not set yet" or "Not assigned yet" means the dispatcher hasn't planned it yet.
   **"No pickup to come. If you've been picked up, you're on your way."** means you have
   nothing still to be collected, including once the driver has picked you up. It does not
   mean your pickup was cancelled.
2. **If your pickup changes,** a **Pickup changed** card shows at the top. It gives:
   - the old and new pickup times;
   - the reason: a flight delay, a vehicle breakdown or a route re-plan.
3. **Tap Acknowledge:** "Acknowledged. The dispatcher can see it." The card goes.
4. **Pull down to refresh.** The app doesn't get notifications, so a change shows only when you open the tab or pull down. Without signal, the screen shows what it last loaded and says so.

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
4. **Moving house?** Send **I need to change my pickup address**. The app never changes your address itself: the dispatcher sets your new home, in the app or in the next roster import. Pickups already planned keep the old one.

### Profile

Open the menu at the top right, then **Profile**. It shows your name, your crew role, your home zone (the pickup area nearest your home), and your next pickup's time and status. It works without signal, showing what it last loaded.

Nothing here can be changed. Your home address comes from the roster, and journey times are worked out per pickup zone, so a pin you set yourself could give a wrong time. To change your address, send **I need to change my pickup address** from the Message tab.
