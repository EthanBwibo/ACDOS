"""Who is calling: the Supabase access token on each request (#52).

The app sends `Authorization: Bearer <Supabase access token>` and nothing
else (no apikey header, no role). The token is checked here against the
project's public signing keys (JWKS, ES256): its signature, audience
(authenticated), issuer (this project's Auth) and expiry. Only public keys
are needed, so the backend holds no auth secret.

What the caller may do comes from profiles.role in the database, never from
the token's claims or the request.
"""

import asyncio
import json
import time
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated
from uuid import UUID

import jwt
from fastapi import Depends, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.errors import ApiError, ErrorCode

ALGORITHMS = ["ES256"]
AUDIENCE = "authenticated"
# An unknown key id triggers a refetch of the keys at most this often, so a
# key rotation is picked up without letting bad tokens hammer Supabase.
REFETCH_AFTER_SEC = 60.0


@dataclass(frozen=True)
class Caller:
    user_id: UUID  # auth.users.id = profiles.id, the token's sub
    claims: dict


class JwksKeys:
    """The project's signing keys, cached by key id (kid).

    An unknown kid means the keys may have rotated: fetch them again, at most
    once per REFETCH_AFTER_SEC, then look again. A kid still unknown is
    rejected.
    """

    def __init__(
        self,
        fetch: Callable[[], dict],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._fetch = fetch  # blocking; returns the JWKS document
        self._clock = clock
        self._keys: dict[str, jwt.PyJWK] = {}
        self._fetched_at: float | None = None
        self._lock = asyncio.Lock()

    async def key(self, kid: str) -> jwt.PyJWK | None:
        if kid in self._keys:
            return self._keys[kid]
        async with self._lock:
            if kid not in self._keys and self._may_fetch():
                await self._refresh()
        return self._keys.get(kid)

    def _may_fetch(self) -> bool:
        return self._fetched_at is None or (self._clock() - self._fetched_at >= REFETCH_AFTER_SEC)

    async def _refresh(self) -> None:
        self._fetched_at = self._clock()
        document = await asyncio.to_thread(self._fetch)
        keys = {}
        for jwk in document.get("keys", []):
            if jwk.get("alg") in ALGORITHMS and "kid" in jwk:
                keys[jwk["kid"]] = jwt.PyJWK(jwk)
        self._keys = keys


def fetch_jwks(supabase_url: str) -> Callable[[], dict]:
    url = f"{supabase_url}/auth/v1/.well-known/jwks.json"

    def fetch() -> dict:
        with urllib.request.urlopen(url, timeout=10) as response:
            return json.load(response)

    return fetch


def issuer(supabase_url: str) -> str:
    return f"{supabase_url}/auth/v1"


def _unauthorized(detail: str) -> ApiError:
    return ApiError(
        status.HTTP_401_UNAUTHORIZED,
        ErrorCode.UNAUTHORIZED,
        detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


# Reads the Authorization header and declares the scheme in the OpenAPI
# contract (bearerAuth, JWT) on every route that depends on caller. With
# auto_error=False it never answers by itself (FastAPI's default would be
# 403): a missing header or another scheme gives None, and caller answers
# 401 like any other bad token.
bearer = HTTPBearer(
    auto_error=False,
    scheme_name="bearerAuth",
    bearerFormat="JWT",
    description="The Supabase session access token.",
)


async def caller(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
) -> Caller:
    """The verified caller, or 401. Every #52 endpoint depends on this."""
    keys: JwksKeys | None = getattr(request.app.state, "jwt_keys", None)
    expected_issuer: str | None = getattr(request.app.state, "jwt_issuer", None)
    if keys is None or expected_issuer is None:
        raise ApiError(
            status.HTTP_503_SERVICE_UNAVAILABLE, ErrorCode.UNAVAILABLE, "SUPABASE_URL is not set"
        )

    if credentials is None or not credentials.credentials:
        raise _unauthorized("missing bearer token")
    token = credentials.credentials
    try:
        kid = jwt.get_unverified_header(token).get("kid")
    except jwt.InvalidTokenError as error:
        raise _unauthorized("malformed token") from error
    key = await keys.key(kid) if kid else None
    if key is None:
        raise _unauthorized("unknown signing key")
    try:
        claims = jwt.decode(
            token,
            key,
            algorithms=ALGORITHMS,
            audience=AUDIENCE,
            issuer=expected_issuer,
            options={"require": ["exp", "sub", "aud", "iss"]},
        )
        return Caller(UUID(claims["sub"]), claims)
    except (jwt.InvalidTokenError, ValueError) as error:
        raise _unauthorized("invalid token") from error


CallerDep = Annotated[Caller, Depends(caller)]
