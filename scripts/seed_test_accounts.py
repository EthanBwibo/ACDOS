"""
ACDOS — test accounts for the Android sign-in flow and API work (#30).

Creates (or brings back in line) one account per role in Supabase Auth, with
its profiles row, and links the crew account to a crew_members row so crew RLS
(private.current_crew_member_id) finds it:

    dispatcher@acdos.test   profiles.role = dispatcher
    driver@acdos.test       profiles.role = driver
    driver2@acdos.test      profiles.role = driver (the spare van's, for the demo)
    driver-101a@acdos.test  profiles.role = driver, demo-KDH 101A's
    driver-102a@acdos.test  profiles.role = driver, demo-KDH 102A's
    driver-103a@acdos.test  profiles.role = driver, demo-KDH 103A's
                            (the demo morning, backend/benchmarks/demo_seed.py)
    crew@acdos.test         profiles.role = crew, crew_members row in Westlands

and the defence demo's accounts (#251), for the 120-crew day of
scripts/make_defence_day.py (#252):

    dispatcher2@acdos.test  a second dispatcher on the same dispatch desk
    amina@ ... halima@      8 named crew, each with a crew_members row holding
                            a staff number and a home in one of 8 zones
                            (NAMED_CREW); the defence day gives them pickups
                            in the bands listed there, so every band has a
                            crew phone to show
    driver-v01@ ... -v20@   one driver per defence van (DEFENCE_VANS)

It prints every account as a table (email, role, crew or van, user id) and
writes the same table, without ids or passwords, to docs/demo_accounts.md.

The app never sets a role: profiles has only SELECT policies, so roles are
written here, with the service role, which bypasses RLS. Safe to re-run: an
existing account keeps its id and gets the password reset to SEED_PASSWORD.

Environment:
    SUPABASE_SERVICE_ROLE_KEY   service role (or sb_secret_...) key. Never commit it.
    SEED_PASSWORD               password for all the accounts (at least 8 characters)
    SUPABASE_URL                defaults to the ACDOS project

Usage (from the repo root):
    python scripts/seed_test_accounts.py
    python scripts/seed_test_accounts.py --tokens   also print a fresh access
                                                    token per account (valid 1 h),
                                                    for calling the API (#52, #54)
"""

import argparse
import csv
import math
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import httpx

DEFAULT_URL = "https://yqqczlvhwlznvaezfpcl.supabase.co"

ACCOUNTS = [
    {
        "email": "dispatcher@acdos.test",
        "role": "dispatcher",
        "full_name": "Test Dispatcher",
    },
    {"email": "driver@acdos.test", "role": "driver", "full_name": "Test Driver"},
    # KDA 002T's driver, for the breakdown in the end-to-end demo (plan_test_route.py).
    {"email": "driver2@acdos.test", "role": "driver", "full_name": "Test Driver 2"},
    # One per demo van (backend/benchmarks/demo_seed.py assigns them by email):
    # the time-limited GA can give any van any stops, so each needs a phone.
    {
        "email": "driver-101a@acdos.test",
        "role": "driver",
        "full_name": "Demo Driver 101A",
    },
    {
        "email": "driver-102a@acdos.test",
        "role": "driver",
        "full_name": "Demo Driver 102A",
    },
    {
        "email": "driver-103a@acdos.test",
        "role": "driver",
        "full_name": "Demo Driver 103A",
    },
    {"email": "crew@acdos.test", "role": "crew", "full_name": "Test Crew"},
    # Several dispatchers share one desk: RLS grants by role, and each reply
    # records its dispatcher (message_replies.dispatcher_id).
    {
        "email": "dispatcher2@acdos.test",
        "role": "dispatcher",
        "full_name": "Grace Wanjiku",
    },
]

# The defence day's time bands (scripts/make_defence_day.py), in day order.
BANDS = ("early", "mid", "noon", "afternoon", "night")


@dataclass(frozen=True)
class NamedCrew:
    """A crew member with a login, among the defence day's 120 crew (#252)."""

    email: str
    name: str
    staff_no: str  # the roster's key: importing this staff number updates this record
    role: str
    zone: str  # a data/pickup_zones.csv label
    east_m: int  # home, in metres east and north of the zone's point
    north_m: int
    bands: tuple[str, ...]  # the bands the defence day gives them a pickup in


# Spread over 8 zones, near and far, and over all 5 bands. Brian is in two
# bands, as some crew are on a real day. Staff numbers KQ300xx stay clear of
# the sample roster's KQ10xxx (docs/roster_sample.csv), so importing that
# file never touches these records. One row per crew member, so not reformatted.
# fmt: off
NAMED_CREW = [
    NamedCrew("amina@acdos.test", "Amina Yusuf", "KQ30001", "cabin_crew",
              "Westlands, Nairobi", 300, -200, ("early",)),
    NamedCrew("brian@acdos.test", "Brian Kiplagat", "KQ30002", "cabin_crew",
              "Embakasi, Nairobi", -250, 300, ("early", "night")),
    NamedCrew("chao@acdos.test", "Chao Lin", "KQ30003", "pilot",
              "Karen, Nairobi", 400, 250, ("mid",)),
    NamedCrew("daniel@acdos.test", "Daniel Mutua", "KQ30004", "cabin_crew",
              "Kasarani, Nairobi", -300, -250, ("mid",)),
    NamedCrew("esther@acdos.test", "Esther Wairimu", "KQ30005", "cabin_crew",
              "South C, Nairobi", 250, 350, ("noon",)),
    NamedCrew("faith@acdos.test", "Faith Chebet", "KQ30006", "cabin_crew",
              "Ruiru, Kiambu County", -350, 200, ("afternoon",)),
    NamedCrew("george@acdos.test", "George Ouma", "KQ30007", "pilot",
              "Kilimani, Nairobi", 200, -300, ("night",)),
    NamedCrew("halima@acdos.test", "Halima Abdi", "KQ30008", "cabin_crew",
              "Kitengela, Kajiado County", -200, -350, ("night",)),
]
# fmt: on

# (plate, driver email, driver name): one driver per defence van of 14 seats.
# make_defence_day.py creates the vans and assigns each its driver by email.
DEFENCE_VANS = [
    (f"defence-KDX {n:03d}", f"driver-v{n:02d}@acdos.test", name)
    for n, name in enumerate(
        [
            "Joseph Kamau",
            "Peter Odhiambo",
            "John Kiprono",
            "Samuel Njoroge",
            "Paul Wekesa",
            "Francis Mwangi",
            "Charles Onyango",
            "Stephen Kibet",
            "Michael Mutiso",
            "David Gitau",
            "Patrick Otieno",
            "Anthony Kariuki",
            "Simon Barasa",
            "James Nyaga",
            "Moses Kiptoo",
            "Isaac Omondi",
            "Kennedy Muriuki",
            "Dennis Wafula",
            "Collins Rotich",
            "Victor Ndegwa",
        ],
        start=1,
    )
]

ACCOUNTS += [
    {"email": c.email, "role": "crew", "full_name": c.name, "named_crew": c}
    for c in NAMED_CREW
]
ACCOUNTS += [
    {"email": email, "role": "driver", "full_name": name, "van": plate}
    for plate, email, name in DEFENCE_VANS
]

ROOT = Path(__file__).resolve().parent.parent
ZONES_CSV = ROOT / "data" / "pickup_zones.csv"
ACCOUNTS_MD = ROOT / "docs" / "demo_accounts.md"

# Westlands from data/pickup_zones.csv. EWKT, which PostgREST passes to the
# geography column as text. Longitude first.
CREW_HOME = "SRID=4326;POINT(36.812022 -1.2675)"
CREW_ROLE = "cabin_crew"


def zone_points() -> dict[str, tuple[float, float]]:
    """(lat, lon) of each pickup zone, from data/pickup_zones.csv."""
    with ZONES_CSV.open(encoding="utf-8", newline="") as f:
        return {
            r["zone"]: (float(r["lat"]), float(r["lon"])) for r in csv.DictReader(f)
        }


def home_of(
    crew: NamedCrew, zones: dict[str, tuple[float, float]]
) -> tuple[float, float]:
    """(lat, lon) of a named crew member's home: their offset from the zone's
    point, treating the Earth as flat, which is close enough over a few
    hundred metres."""
    lat, lon = zones[crew.zone]
    dlat = crew.north_m / 111_320
    dlon = crew.east_m / (111_320 * math.cos(math.radians(lat)))
    return round(lat + dlat, 6), round(lon + dlon, 6)


def describe(account: dict) -> str:
    """The table's third column: the crew member or the van."""
    if "named_crew" in account:
        c = account["named_crew"]
        return f"{c.name} ({c.staff_no}), {c.zone.split(',')[0]}, {' + '.join(c.bands)}"
    if "van" in account:
        return f"{account['full_name']}, {account['van']}"
    return account["full_name"]


def accounts_table(ids: dict[str, str] | None = None) -> str:
    """Every account as a Markdown table, with a user id column when given."""
    head = ["Email", "Role", "Crew or van"] + (["User id"] if ids is not None else [])
    lines = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    for a in ACCOUNTS:
        cells = [a["email"], a["role"], describe(a)]
        if ids is not None:
            cells.append(ids.get(a["email"], ""))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def accounts_markdown() -> str:
    """docs/demo_accounts.md: the table with no user ids and no passwords."""
    return (
        "# Demo accounts\n\n"
        "Written by `scripts/seed_test_accounts.py` (#251); do not edit by hand. "
        "Every password is the `SEED_PASSWORD` the script was run with, which is "
        "not recorded here. A crew row gives the crew member, staff number, home "
        "zone, and the bands of the defence day (`scripts/make_defence_day.py`) "
        "they have a pickup in. A driver row gives the van they drive.\n\n"
        "Bands, report times at JKIA in Nairobi time: early 04:00-06:30, "
        "mid 08:00-10:00, noon 11:30-13:30, afternoon 15:00-17:30, "
        "night 20:00-23:00.\n\n" + accounts_table()
    )


def headers(key: str) -> dict[str, str]:
    h = {"apikey": key}
    # New-style sb_secret_ keys are not JWTs: the gateway accepts them only in
    # the apikey header. Legacy service_role keys are JWTs and go in both.
    if not key.startswith("sb_"):
        h["Authorization"] = f"Bearer {key}"
    return h


def find_user_id(client: httpx.Client, email: str) -> str:
    page = 1
    while True:
        r = client.get("/auth/v1/admin/users", params={"page": page, "per_page": 200})
        r.raise_for_status()
        users = r.json()["users"]
        for user in users:
            if user.get("email") == email:
                return user["id"]
        if len(users) < 200:
            raise SystemExit(
                f"{email}: exists in Auth but was not found in the user list"
            )
        page += 1


def ensure_user(client: httpx.Client, email: str, password: str, full_name: str) -> str:
    r = client.post(
        "/auth/v1/admin/users",
        json={
            "email": email,
            "password": password,
            "email_confirm": True,
            "user_metadata": {"full_name": full_name},
        },
    )
    if r.status_code == 200:
        return r.json()["id"]
    if r.status_code == 422 and r.json().get("error_code") == "email_exists":
        user_id = find_user_id(client, email)
        client.put(
            f"/auth/v1/admin/users/{user_id}", json={"password": password}
        ).raise_for_status()
        return user_id
    raise SystemExit(f"{email}: could not create the user ({r.status_code}): {r.text}")


def upsert(client: httpx.Client, table: str, conflict: str, row: dict) -> None:
    r = client.post(
        f"/rest/v1/{table}",
        params={"on_conflict": conflict},
        headers={"Prefer": "resolution=merge-duplicates,return=minimal"},
        json=row,
    )
    if r.is_error:
        raise SystemExit(f"{table}: upsert failed ({r.status_code}): {r.text}")


def access_token(client: httpx.Client, email: str, password: str) -> str:
    r = client.post(
        "/auth/v1/token",
        params={"grant_type": "password"},
        json={"email": email, "password": password},
    )
    r.raise_for_status()
    return r.json()["access_token"]


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--tokens", action="store_true", help="print an access token per account"
    )
    args = parser.parse_args()

    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    password = os.environ.get("SEED_PASSWORD")
    url = os.environ.get("SUPABASE_URL", DEFAULT_URL).rstrip("/")
    if not key or not password:
        sys.exit("Set SUPABASE_SERVICE_ROLE_KEY and SEED_PASSWORD (see the docstring).")
    if len(password) < 8:
        sys.exit("SEED_PASSWORD must be at least 8 characters.")

    zones = zone_points()
    ids: dict[str, str] = {}
    with httpx.Client(base_url=url, headers=headers(key), timeout=30) as client:
        for account in ACCOUNTS:
            user_id = ensure_user(
                client, account["email"], password, account["full_name"]
            )
            ids[account["email"]] = user_id
            upsert(
                client,
                "profiles",
                "id",
                {
                    "id": user_id,
                    "role": account["role"],
                    "full_name": account["full_name"],
                },
            )
            if "named_crew" in account:
                c = account["named_crew"]
                lat, lon = home_of(c, zones)
                # Keyed on the staff number: a crew record that a roster
                # import made first for this staff number gets linked to the
                # account, instead of a second record being added.
                upsert(
                    client,
                    "crew_members",
                    "staff_no",
                    {
                        "profile_id": user_id,
                        "staff_no": c.staff_no,
                        "name": c.name,
                        "role": c.role,
                        "home_location": f"SRID=4326;POINT({lon} {lat})",
                    },
                )
            elif account["role"] == "crew":
                upsert(
                    client,
                    "crew_members",
                    "profile_id",
                    {
                        "profile_id": user_id,
                        "name": account["full_name"],
                        "role": CREW_ROLE,
                        "home_location": CREW_HOME,
                    },
                )
            if args.tokens:
                token = access_token(client, account["email"], password)
                print(f"{account['email']} access token: {token}")

    print(accounts_table(ids))
    ACCOUNTS_MD.write_text(accounts_markdown(), encoding="utf-8")
    print(f"Wrote {ACCOUNTS_MD.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
