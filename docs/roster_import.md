# Roster CSV import

The roster is an external input: ACDOS does not build it. The dispatcher puts it in with a CSV
file (#229), from **Pickups > Import roster** in the app, or `POST /roster-imports`. One row is
one rostered pickup. A sample is in [`roster_sample.csv`](roster_sample.csv). Change its dates
to future ones before importing it, because rows with a past report time are rejected.

## Columns

The first line is the header. Column names ignore case and surrounding spaces, and the columns
can be in any order.

| Column | Required | Format |
|---|---|---|
| `staff_no` | yes | The airline's staff number. It identifies the crew member across imports. |
| `name` | yes | Full name, as the screens show it. |
| `crew_role` | yes | Free text, e.g. `cabin_crew` or `pilot`. |
| `pickup_lat` | yes | Latitude in decimal degrees, e.g. `-1.289279`. |
| `pickup_lon` | yes | Longitude in decimal degrees, e.g. `36.786931`. |
| `report_time` | yes | When they must report at JKIA: ISO 8601 with a UTC offset, e.g. `2026-11-25T05:30:00+03:00`. A time without an offset is rejected, because it could be Nairobi time or UTC. |
| `request_type` | no | `rostered` or `standby`. Empty or missing means `rostered`. |

Text values are at most 200 characters. The file is UTF-8, as Excel saves "CSV UTF-8", with or
without a byte order mark. It has at most 500 rows and 256 KB. Blank lines are ignored.

## What an import does

- **Crew:** matched by `staff_no`.
  - A new staff number creates a crew member, with their first pickup point in the file as their
    home location.
  - A known staff number gets its name and role updated from the file. Its home location stays as
    it was, because a pickup point can be a one-off, such as a hotel.
  - If one staff number appears on several rows, its first row gives the name and role.
- **Pickups:** one `pickup_requests` row per accepted CSV row, with status `pending`.
- **No re-plan.** Importing never starts optimisation. The dispatcher plans with the new pickups
  as usual.

All of an import's writes happen in one transaction.

## Rows that are rejected

Each one is skipped and reported with its line number (the header is line 1) and a reason. The
other rows still import.

| Reason | When |
|---|---|
| `invalid_row` | A required field is missing or can't be read: not a number, a latitude out of range, a time without an offset, an unknown request type, or more fields than columns. The detail names the field. |
| `outside_pickup_zones` | The pickup point is more than 10 km from every one of the 28 pickup zones. This is checked in PostGIS with `ST_DWithin` on geography. |
| `report_time_past` | The report time has already passed. |
| `duplicate_pickup` | The same staff number and report time appear earlier in the file, or that crew member already has a pickup at that report time (cancelled pickups don't count). The same instant written with a different offset is still a duplicate. |

## Whole-file errors

These are answered with 422 `validation_failed`, and nothing is imported:
- the file is empty, not UTF-8, or missing a required column;
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

For example, importing the sample with Daniel Otieno's pickup point moved out to Nakuru:

```json
{
  "dry_run": false,
  "rows": 5,
  "crew_created": 3,
  "crew_updated": 0,
  "pickups_created": 4,
  "rows_rejected": 1,
  "rejected": [
    {"line": 6, "staff_no": "KQ11044", "reason": "outside_pickup_zones",
     "detail": "over 10 km from every pickup zone"}
  ]
}
```
