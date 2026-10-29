"""
ACDOS — test accounts for the Android sign-in flow and API work (#30).

Creates (or brings back in line) one account per role in Supabase Auth, with
its profiles row, and links the crew account to a crew_members row so crew RLS
(private.current_crew_member_id) finds it:

    dispatcher@acdos.test   profiles.role = dispatcher
    driver@acdos.test       profiles.role = driver
    crew@acdos.test         profiles.role = crew, crew_members row in Westlands

The app never sets a role: profiles has only SELECT policies, so roles are
written here, with the service role, which bypasses RLS. Safe to re-run: an
existing account keeps its id and gets the password reset to SEED_PASSWORD.

Environment:
    SUPABASE_SERVICE_ROLE_KEY   service role (or sb_secret_...) key. Never commit it.
    SEED_PASSWORD               password for all three accounts (at least 8 characters)
    SUPABASE_URL                defaults to the ACDOS project

Usage (from the repo root):
    python scripts/seed_test_accounts.py
    python scripts/seed_test_accounts.py --tokens   also print a fresh access
                                                    token per account (valid 1 h),
                                                    for calling the API (#52, #54)
"""

import argparse
import os
import sys

import httpx

DEFAULT_URL = "https://yqqczlvhwlznvaezfpcl.supabase.co"

ACCOUNTS = [
    {"email": "dispatcher@acdos.test", "role": "dispatcher", "full_name": "Test Dispatcher"},
    {"email": "driver@acdos.test", "role": "driver", "full_name": "Test Driver"},
    {"email": "crew@acdos.test", "role": "crew", "full_name": "Test Crew"},
]

# Westlands from data/pickup_zones.csv. EWKT, which PostgREST passes to the
# geography column as text. Longitude first.
CREW_HOME = "SRID=4326;POINT(36.812022 -1.2675)"
CREW_ROLE = "cabin_crew"


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
            raise SystemExit(f"{email}: exists in Auth but was not found in the user list")
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
    parser.add_argument("--tokens", action="store_true", help="print an access token per account")
    args = parser.parse_args()

    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    password = os.environ.get("SEED_PASSWORD")
    url = os.environ.get("SUPABASE_URL", DEFAULT_URL).rstrip("/")
    if not key or not password:
        sys.exit("Set SUPABASE_SERVICE_ROLE_KEY and SEED_PASSWORD (see the docstring).")
    if len(password) < 8:
        sys.exit("SEED_PASSWORD must be at least 8 characters.")

    with httpx.Client(base_url=url, headers=headers(key), timeout=30) as client:
        for account in ACCOUNTS:
            user_id = ensure_user(client, account["email"], password, account["full_name"])
            upsert(
                client,
                "profiles",
                "id",
                {"id": user_id, "role": account["role"], "full_name": account["full_name"]},
            )
            if account["role"] == "crew":
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
            print(f"{account['role']:<10} {account['email']:<22} {user_id}")
            if args.tokens:
                print(f"  access token: {access_token(client, account['email'], password)}")


if __name__ == "__main__":
    main()
