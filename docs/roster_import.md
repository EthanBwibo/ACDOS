# Roster CSV import

The roster is an external input: ACDOS does not build it. The dispatcher puts it in with a CSV
file (#229), from **Pickups > Import roster** in the app, or `POST /roster-imports`. One row is
one rostered pickup. To start a roster from scratch, use the template:
**Download template** on Import roster saves it, and the same file is
[`acdos_roster_template.csv`](acdos_roster_template.csv). It has the headers and two example
rows: one with a blank location (a known crew member, collected from home) and one with a
point pasted from Google Maps. A sample is in [`roster_sample.csv`](roster_sample.csv): six good rows and
five bad ones. Most of its rows have no location; two new crew members give one, pasted from
Google Maps as coordinates and as a link. The last row moves one of them home with
`set_home`. Rows with a
past report time are rejected, so regenerate it with report times from tomorrow (Nairobi)
before importing it:

```
python scripts/make_sample_roster.py                    # from tomorrow
python scripts/make_sample_roster.py --date 2026-12-01  # from a given day
```

## Columns

The first line is the header. The columns can be in any order. Headers are matched ignoring
case, spaces, underscores and hyphens, so `Staff No`, `staff_no` and `STAFF-NO` are the same
column, and each column also accepts the names a spreadsheet may already use (#254):

| Column | Also accepted |
|---|---|
| `staff_no` | staff number, staff no, staff id, employee no |
| `crew_role` | role, rank |
| `pickup_location` | location, pickup point, pickup, coordinates |
| `report_time` | report, report at, duty time |
| `request_type` | type |
| `set_home` | new home, move home |

Any other column is ignored. Two headers for the same column, e.g. `Role` and `crew_role`, are
refused, rather than one of them being read without a word.

| Column | Required | Format |
|---|---|---|
| `staff_no` | yes | The airline's staff number. It identifies the crew member across imports. |
| `name` | yes | Full name, as the screens show it. |
| `crew_role` | yes | Free text, e.g. `cabin_crew` or `pilot`. |
| `pickup_location` | no | Where to collect them, pasted from Google Maps (see below): `lat, lon` in decimal degrees, e.g. `-1.292533, 36.787543`, or a Google Maps link with the point in it. Blank means their home location. A new crew member needs one on at least one row. |
| `report_time` | yes | When they must report at JKIA: ISO 8601 with a UTC offset, e.g. `2026-11-25T05:30:00+03:00`. A time without an offset is rejected, because it could be Nairobi time or UTC. |
| `request_type` | no | `rostered` or `standby`. Empty or missing means `rostered`. |
| `set_home` | no | `yes` or blank. `yes` makes this row's `pickup_location` the crew member's home as well (see below). Blank or missing: the point is for this pickup only. |

The column and every value in it may be left out or blank. A value with a comma in it, as both
forms of `pickup_location` have, must be in double quotes in the CSV. Excel and Google Sheets
add them when they save. `pickup_lat` and `pickup_lon` were replaced by `pickup_location`
(#245): a file that still has them is refused as a whole, rather than every row falling back
to a home location.

Text values are at most 200 characters, and `pickup_location` at most 2,000 (Maps links are
long). The file is UTF-8, as Excel saves "CSV UTF-8", with or
without a byte order mark. It has at most 500 rows and 256 KB. Blank lines are ignored.

## What an import does

- **Crew:** matched by `staff_no`.
  - A new staff number creates a crew member, with their first accepted pickup point in the
    file as their home location. Without one, their rows are rejected as `no_pickup_location`.
  - A known staff number gets its name and role updated from the file. Its home location stays as
    it was, because a pickup point can be a one-off, such as a hotel, unless a row says
    `set_home` = `yes`.
  - **`set_home` = `yes`** moves the crew member's home to that row's point **from that row's
    report time on**, as well as using it for that pickup. Where the row is in the file doesn't
    matter: only its report time does. Several moves for one person chain in report-time order.
    The stored home ends up as the move with the latest report time. Each move is listed in
    `home_moves` (with `takes_effect`, its report time) and counted in `homes_updated`. A
    `set_home` row that is rejected moves nothing.
  - **A new crew member's first home** is their first point in the file without `set_home`, in
    line order, or, if every point they have says `set_home`, the earliest of those. Their other
    `set_home` rows are moves from it.
  - If one staff number appears on several rows, its first row gives the name and role.
- **Pickups:** one `pickup_requests` row per accepted CSV row, with status `pending`. A row with
  a `pickup_location` is collected there. A row without one is collected from the home in effect
  at its report time: the point of the latest `set_home` row for the same crew member whose
  report time is at or before this row's, or, if there is none, their stored home (a new crew
  member's first home). `home_uses` says which home each such row uses.
- **No re-plan.** Importing never starts optimisation. The dispatcher plans with the new pickups
  as usual.

All of an import's writes happen in one transaction.

## Rows that are rejected

Each one is skipped and reported with its line number (the header is line 1) and a reason. The
other rows still import.

| Reason | When |
|---|---|
| `invalid_row` | A required field is missing or can't be read: a time without an offset, an unknown request type, more fields than columns (often a `lat, lon` without quotes), or a `pickup_location` that isn't a `lat, lon` pair or a Google Maps link with coordinates in it. The detail names the field and the problem. |
| `outside_pickup_zones` | The pickup point is more than 10 km from every one of the 28 pickup zones. This is checked in PostGIS with `ST_DWithin` on geography. |
| `no_pickup_location` | A new crew member, and none of their accepted rows gives a `pickup_location`, so there is no home to collect them from. The detail says "new crew member needs a pickup location". |
| `set_home_needs_location` | `set_home` is `yes` but the row has no `pickup_location`: there is no point to move the home to. |
| `report_time_past` | The report time has already passed. |
| `duplicate_pickup` | The same staff number and report time appear earlier in the file, or that crew member already has a pickup at that report time (cancelled pickups don't count). The same instant written with a different offset is still a duplicate. |

## Getting a pickup point from Google Maps

Either form can be pasted into the `pickup_location` cell.

**Coordinates (the most reliable):**
1. Open [Google Maps](https://www.google.com/maps) on a computer and find the pickup point: the
   gate or building entrance where the van should stop.
2. Right-click exactly on that spot. The first line of the menu is its coordinates, e.g.
   `-1.292533, 36.787543`.
3. Click them. Maps copies them, and says so.
4. Paste into the cell. Keep the comma: latitude first, then longitude.

On a phone: touch and hold the spot to drop a pin. The coordinates show in the search box at
the top; tap them, or copy them from the pin's details.

**A link:** a link to a place or a dropped pin works too, copied from the browser's address bar
or with Share > Copy link on a computer, e.g.

```
https://www.google.com/maps/place/1%C2%B015'38.1%22S+36%C2%B048'08.0%22E/@-1.2605758,36.7996421,17z/data=!3m1!4b1!4m4!3m3!8m2!3d-1.260581!4d36.802217
```

The import reads the point from the link, most precise first:
- the pin, `!3d<lat>!4d<lon>`;
- a point given outright: `?q=`, `?query=`, `?ll=`, `?destination=`, or `/place/<lat>,<lon>`;
- the centre of the map view, `@<lat>,<lon>`. It is only where the map was looking, so if
  the link has nothing else, check the distance the dry run shows.

**What doesn't work:**
- **Short links** (`https://maps.app.goo.gl/...`, which the phone app's Share gives). They have
  no coordinates in them, and the import doesn't follow links. Open the link in a browser and
  copy the full address, or copy the coordinates.
- **A place name or an address**, e.g. `Sarit Centre`. Those aren't read: names are ambiguous,
  and looking them up would need a geocoding service.
- **Degrees, minutes and seconds**, e.g. `1°15'38.1"S 36°48'08.0"E`. Copy the decimal pair instead.
- **Links from other map sites.**

Each of these rejects the row as `invalid_row`, with the reason in the detail.

**Moving someone's home:** paste the new point as above and put `yes` in that row's `set_home`
cell. Put it on their first pickup from the new address: the move takes effect at that row's
report time, so their earlier pickups in the roster still go to the old home, and later ones to
the new. The dry run shows:
- the move, e.g. "Home moves: Kilimani → Kasarani (14.1 km, from Fri 20 Nov)";
- for each row with no location, which home it uses, e.g. "home (Kilimani)" or "home (Kasarani,
  from Fri 20 Nov)".

A wrong point or a wrong date is caught there, before it changes anything. Without `yes`, the
point is for that one pickup, as for a hotel.

**Check before importing.** The dry run lists every row's nearest zone and the distance to it
(see Response). A point a few kilometres from its zone is normal. One that is far out, or in
the wrong zone, is usually a typo, or latitude and longitude swapped. More than 10 km from
every zone is rejected anyway.

## Whole-file errors

These are answered with 422 `validation_failed`, and nothing is imported:
- the file is empty, or not UTF-8;
- a required column is missing. The detail names it and lists the headers found, e.g. "No
  staff_no column. Found: Name, Role, Location, Report";
- two headers are the same column;
- the file still has the old `pickup_lat` and `pickup_lon` columns, however their headers are
  written;
- the file has over 500 rows;
- a real import is sent without an `Idempotency-Key`.

A file over 256 KB gets 413 `payload_too_large`.

## Dry run, then import

The app always runs a dry run first: `POST /roster-imports?dry_run=true`. That runs the same
checks and writes inside a savepoint, then rolls them back. The counts and rejected rows it
returns are exactly what the import would do. The dispatcher then confirms with "Import N
pickups", which sends the same file without `dry_run`.

A real import needs an `Idempotency-Key` header. The result is stored under that key in
`roster_imports`. A retry with the same key and the same file gets that stored result and
imports nothing more, so a dropped connection can't import a roster twice. The same key with a
different file is refused with 422 `idempotency_key_reused`.

## Response

Importing the sample once, with none of its crew known yet:

```json
{
  "dry_run": false,
  "rows": 11,
  "crew_created": 2,
  "crew_updated": 0,
  "pickups_created": 6,
  "rows_rejected": 5,
  "rejected": [
    {"line": 7, "staff_no": "KQ10457", "reason": "duplicate_pickup",
     "detail": "the same pickup is on line 4"},
    {"line": 8, "staff_no": "KQ11290", "reason": "outside_pickup_zones",
     "detail": "over 10 km from every pickup zone"},
    {"line": 9, "staff_no": "KQ11317", "reason": "report_time_past",
     "detail": "report_time: already past"},
    {"line": 10, "staff_no": "KQ11402", "reason": "invalid_row",
     "detail": "report_time: needs a UTC offset, e.g. +03:00"},
    {"line": 11, "staff_no": "KQ10892", "reason": "no_pickup_location",
     "detail": "new crew member needs a pickup location"}
  ],
  "locations": [
    {"line": 2, "staff_no": "KQ10231", "zone_label": "Kilimani, Nairobi", "distance_km": 0.4},
    {"line": 4, "staff_no": "KQ10457", "zone_label": "Westlands, Nairobi", "distance_km": 1.3},
    {"line": 8, "staff_no": "KQ11290", "zone_label": "Runda, Nairobi", "distance_km": 129.9},
    {"line": 12, "staff_no": "KQ10231", "zone_label": "Kasarani, Nairobi", "distance_km": 0.7}
  ],
  "homes_updated": 1,
  "home_moves": [
    {"line": 12, "staff_no": "KQ10231", "from_zone": "Kilimani, Nairobi",
     "to_zone": "Kasarani, Nairobi", "distance_km": 14.1,
     "takes_effect": "2026-11-20T20:00:00+03:00"}
  ],
  "home_uses": [
    {"line": 3, "staff_no": "KQ10231", "zone_label": "Kilimani, Nairobi", "since": null},
    {"line": 5, "staff_no": "KQ10457", "zone_label": "Westlands, Nairobi", "since": null},
    {"line": 6, "staff_no": "KQ10231", "zone_label": "Kasarani, Nairobi",
     "since": "2026-11-20T20:00:00+03:00"}
  ]
}
```

- **`locations`** has every row read with a `pickup_location`, rejected ones included, with its
  nearest pickup zone and the distance to it. Both are worked out in PostGIS, to 0.1 km. Rows
  with no location, and rows rejected before their location could be read, aren't listed.
- **Two crew are created.** Amina's point (line 2) and Brian's link (line 4) become their
  homes.
- **Line 12 moves Amina's home** to Kasarani (`set_home` = `yes`) from its report time, 20:00
  on 20 November. It's the last line, but it takes effect at that time. Each move gives the zones nearest the old and new home and
  the distance between them, from PostGIS.
- **Rows with no location** use the home in effect at their report time (`home_uses`):
  - line 3 (Amina, 20 Nov 05:30, before the move): her Kilimani point;
  - line 5 (Brian): his Westlands point;
  - line 6 (Amina, 21 Nov, after the move): Kasarani.

  Amina's stored home ends up at Kasarani.
- **Lines 8 and 11 are rejected by the database checks** (zone, then home); the others while
  the file is read.

Importing the same file again, under a new key, rejects the six good rows too, as
`duplicate_pickup`: those crew already have pickups at those times. Line 12 is one of them, so
it moves no home.
