"""Checking Supabase access tokens (#52): app/auth.py.

A small app with one endpoint behind the caller dependency, so these need
no database.
"""

import time
from uuid import uuid4

import jwt
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import errors
from app.auth import REFETCH_AFTER_SEC, CallerDep
from tests.jwt_keys import ISSUER, FakeJwks, SigningKey, bearer

KEY = SigningKey("key-1")


def make_client(jwks: FakeJwks, clock=time.monotonic) -> TestClient:
    app = FastAPI()
    errors.install(app)
    app.state.jwt_keys = jwks.source(clock)
    app.state.jwt_issuer = ISSUER

    @app.get("/whoami")
    async def whoami(caller: CallerDep) -> dict:
        return {"user_id": str(caller.user_id)}

    return TestClient(app)


@pytest.fixture
def jwks():
    return FakeJwks(KEY)


@pytest.fixture
def client(jwks):
    return make_client(jwks)


def test_a_valid_token_gives_its_subject(client):
    user = uuid4()
    response = client.get("/whoami", headers=bearer(KEY.token(user)))
    assert response.status_code == 200
    assert response.json() == {"user_id": str(user)}


@pytest.mark.parametrize(
    "headers",
    [{}, {"Authorization": "Basic abc"}, {"Authorization": "Bearer "}, bearer("not-a-jwt")],
    ids=["none", "not bearer", "empty", "malformed"],
)
def test_no_usable_token_is_401(client, headers):
    response = client.get("/whoami", headers=headers)
    assert response.status_code == 401
    assert response.headers["WWW-Authenticate"] == "Bearer"
    assert response.json()["code"] == "unauthorized"


@pytest.mark.parametrize(
    "claims",
    [
        {"exp": int(time.time()) - 10},
        {"aud": "anon"},
        {"iss": "https://another-project.supabase.co/auth/v1"},
        {"sub": None},
        {"exp": None},
        {"sub": "not-a-uuid"},
    ],
    ids=["expired", "wrong audience", "wrong issuer", "no subject", "no expiry", "bad subject"],
)
def test_a_token_with_wrong_claims_is_401(client, claims):
    claims = dict(claims)
    subject = claims.pop("sub", uuid4())  # None: the claim is left out
    response = client.get("/whoami", headers=bearer(KEY.token(subject, **claims)))
    assert response.status_code == 401


def test_a_valid_token_under_another_scheme_is_401(client):
    headers = {"Authorization": f"Basic {KEY.token(uuid4())}"}
    assert client.get("/whoami", headers=headers).status_code == 401


def test_a_token_signed_by_another_key_with_a_known_kid_is_401(client):
    impostor = SigningKey(KEY.kid)  # same kid, different private key
    assert client.get("/whoami", headers=bearer(impostor.token(uuid4()))).status_code == 401


def test_an_hs256_token_is_401(client):
    # Signed with a shared secret instead of the project's key: the
    # algorithm is not accepted, whatever the secret.
    token = jwt.encode(
        {"sub": str(uuid4()), "aud": "authenticated", "iss": ISSUER, "exp": time.time() + 60},
        "a-shared-secret-of-at-least-32-bytes",
        algorithm="HS256",
        headers={"kid": KEY.kid},
    )
    assert client.get("/whoami", headers=bearer(token)).status_code == 401


def test_keys_are_fetched_once_and_cached(client, jwks):
    for _ in range(3):
        assert client.get("/whoami", headers=bearer(KEY.token(uuid4()))).status_code == 200
    assert jwks.fetches == 1


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_a_rotated_key_is_picked_up_by_one_refetch():
    jwks, clock = FakeJwks(KEY), Clock()
    client = make_client(jwks, clock)
    assert client.get("/whoami", headers=bearer(KEY.token(uuid4()))).status_code == 200

    # Supabase rotates to a new key; a token signed with it arrives later.
    new_key = SigningKey("key-2")
    jwks.keys.append(new_key)
    clock.now += REFETCH_AFTER_SEC

    assert client.get("/whoami", headers=bearer(new_key.token(uuid4()))).status_code == 200
    assert jwks.fetches == 2


def test_unknown_kids_refetch_at_most_once_per_interval():
    jwks, clock = FakeJwks(KEY), Clock()
    client = make_client(jwks, clock)
    client.get("/whoami", headers=bearer(KEY.token(uuid4())))  # first fetch

    clock.now += REFETCH_AFTER_SEC
    stranger = SigningKey("never-published")
    for _ in range(5):
        response = client.get("/whoami", headers=bearer(stranger.token(uuid4())))
        assert response.status_code == 401
    # One refetch for the five, not five: bad tokens can't hammer Supabase.
    assert jwks.fetches == 2

    # Within the interval, even a real new key waits for the next refetch.
    new_key = SigningKey("key-2")
    jwks.keys.append(new_key)
    assert client.get("/whoami", headers=bearer(new_key.token(uuid4()))).status_code == 401
    clock.now += REFETCH_AFTER_SEC
    assert client.get("/whoami", headers=bearer(new_key.token(uuid4()))).status_code == 200


def test_without_keys_configured_the_endpoints_are_unavailable():
    app = FastAPI()
    errors.install(app)

    @app.get("/whoami")
    async def whoami(caller: CallerDep) -> dict:
        return {}

    response = TestClient(app).get("/whoami", headers=bearer(KEY.token(uuid4())))
    assert response.status_code == 503
    assert response.json()["code"] == "unavailable"
