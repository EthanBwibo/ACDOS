"""The defence demo's accounts (#251, scripts/seed_test_accounts.py): what
the script would create, checked without calling Supabase."""

import importlib.util
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "seed_test_accounts", ROOT / "scripts" / "seed_test_accounts.py"
)
accounts = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(accounts)


def test_every_email_is_one_account():
    emails = [a["email"] for a in accounts.ACCOUNTS]
    assert len(emails) == len(set(emails))


def test_there_is_a_second_dispatcher():
    dispatchers = [a["email"] for a in accounts.ACCOUNTS if a["role"] == "dispatcher"]
    assert dispatchers == ["dispatcher@acdos.test", "dispatcher2@acdos.test"]


def test_eight_named_crew_with_their_own_staff_numbers():
    crew = accounts.NAMED_CREW
    assert [c.email.split("@")[0] for c in crew] == [
        "amina",
        "brian",
        "chao",
        "daniel",
        "esther",
        "faith",
        "george",
        "halima",
    ]
    assert len({c.staff_no for c in crew}) == 8
    # Clear of the sample roster's staff numbers, so importing it never
    # renames or moves a named crew member.
    sample = (ROOT / "docs" / "roster_sample.csv").read_text(encoding="utf-8")
    assert not any(c.staff_no in sample for c in crew)


def test_every_band_has_a_crew_phone():
    for band in accounts.BANDS:
        assert any(band in c.bands for c in accounts.NAMED_CREW), band
    assert all(set(c.bands) <= set(accounts.BANDS) for c in accounts.NAMED_CREW)


def test_homes_are_in_eight_zones_and_near_their_zone():
    zones = accounts.zone_points()
    assert len({c.zone for c in accounts.NAMED_CREW}) == 8
    for c in accounts.NAMED_CREW:
        lat, lon = accounts.home_of(c, zones)
        zlat, zlon = zones[c.zone]
        # Metres, flat Earth: fine at this scale. Well inside the 10 km the
        # import allows.
        north = (lat - zlat) * 111_320
        east = (lon - zlon) * 111_320 * math.cos(math.radians(zlat))
        assert abs(north - c.north_m) < 1 and abs(east - c.east_m) < 1
        assert (north**2 + east**2) ** 0.5 < 1_000


def test_one_driver_per_defence_van():
    vans = accounts.DEFENCE_VANS
    assert len(vans) == 20
    assert vans[0][:2] == ("defence-KDX 001", "driver-v01@acdos.test")
    assert vans[-1][:2] == ("defence-KDX 020", "driver-v20@acdos.test")
    assert len({plate for plate, _, _ in vans}) == 20
    assert len({email for _, email, _ in vans}) == 20
    drivers = {a["email"] for a in accounts.ACCOUNTS if a["role"] == "driver"}
    assert {email for _, email, _ in vans} <= drivers


def test_the_docs_table_is_current_and_has_no_passwords():
    md = (ROOT / "docs" / "demo_accounts.md").read_text(encoding="utf-8")
    assert md == accounts.accounts_markdown()
    # One row per account, after the header and its rule.
    rows = [line for line in md.splitlines() if line.startswith("| ")]
    assert len(rows) == 1 + len(accounts.ACCOUNTS)
    assert "SEED_PASSWORD" in md and "password |" not in md.lower()


def test_the_printed_table_has_the_user_ids():
    table = accounts.accounts_table({"amina@acdos.test": "1234"})
    assert "| Email | Role | Crew or van | User id |" in table
    assert "| amina@acdos.test | crew | Amina Yusuf (KQ30001), Westlands, early | 1234 |" in table
