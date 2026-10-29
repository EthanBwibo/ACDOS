"""The #52 endpoints without a database: the token is checked first."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.config import settings
from app.main import app
from tests.jwt_keys import ISSUER, FakeJwks, SigningKey, bearer

KEY = SigningKey("test-key")
PATHS = ["/drivers/me/route", "/drivers/me/routes", "/crew/me/pickup"]


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(settings, "database_url", None)
    monkeypatch.setattr(app.state, "jwt_keys", FakeJwks(KEY).source(), raising=False)
    monkeypatch.setattr(app.state, "jwt_issuer", ISSUER, raising=False)
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("path", PATHS)
def test_without_a_token_it_is_401_even_without_a_database(client, path):
    assert client.get(path).status_code == 401


@pytest.mark.parametrize("path", PATHS)
def test_with_a_valid_token_but_no_database_it_is_503(client, path):
    assert client.get(path, headers=bearer(KEY.token(uuid4()))).status_code == 503
