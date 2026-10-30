# Contributing to ACDOS

Solo-maintained capstone project. This document exists to keep the workflow consistent
across sessions rather than to onboard external contributors.

## Branching

`main` is protected: no direct pushes, no force-pushes, no branch deletion. All work
lands via pull request.

Branch names are prefixed by component:

```
solver/ga-chromosome-encoding
rf/temporal-calibration
android/room-schema
sync/event-sourcing-queue
docs/chapter-3-writeup
```

## Commit messages — Conventional Commits, six types

Format: `type(scope): summary`

| Type | Use for |
|---|---|
| `feat` | New capability |
| `fix` | Bug fix |
| `refactor` | Restructuring without behaviour change |
| `test` | Adding or fixing tests |
| `docs` | Documentation, chapter drafts, design artefact updates |
| `chore` | Tooling, dependencies, CI config, housekeeping |

Examples:
```
feat(solver): implement Shaw removal operator
fix(sync): correct idempotency key derivation
docs(ch3): document synthetic trip_records rationale
```

Enable the local hook so malformed messages are rejected before they land:
```bash
git config core.hooksPath .githooks
```

## Pull requests

- One PR per issue/task where practical.
- Squash-merge only — `main` history stays linear, one commit per merged PR.
- Delete the branch after merge.
- Link the PR to its milestone issue.

## API contract

`docs/openapi.json` is the backend's API contract, which the Android client is built against
(#122). After changing a route or any request, response or error model, regenerate it and
commit it with the change:

```bash
cd backend && python -m app.contract --write
```

`pytest` fails while the committed file is stale, and so does CI. `python -m app.contract
--check` gives the same answer without running the tests.

## Issue labels

- `type:feature`, `type:bug`, `type:chore`, `type:docs`, `type:test`
- `component:backend`, `component:android`, `component:database`
- `pillar:ga-alns`, `pillar:random-forest`, `pillar:event-sourcing`

## Milestones

Work is organised M1 through M8 (scaffolding → GA-ALNS core → RF service → Android
client → offline sync → integration → final documentation → defence prep). See the
project board for current status.
