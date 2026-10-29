"""Test access tokens for the #52 endpoints, signed like Supabase's (ES256)
with a key made for the test run, so no test needs a real account (#30) or
any secret."""

import json
import time
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric import ec
from jwt.algorithms import ECAlgorithm

from app.auth import JwksKeys

ISSUER = "https://test-project.supabase.co/auth/v1"


class SigningKey:
    def __init__(self, kid: str) -> None:
        self.kid = kid
        self.private = ec.generate_private_key(ec.SECP256R1())

    def jwk(self) -> dict:
        public = json.loads(ECAlgorithm.to_jwk(self.private.public_key()))
        return public | {"kid": self.kid, "alg": "ES256", "use": "sig"}

    def token(self, sub: UUID | str | None, **overrides) -> str:
        """None for a claim (sub included) leaves it out."""
        now = int(time.time())
        claims = {
            "sub": None if sub is None else str(sub),
            "aud": "authenticated",
            "iss": ISSUER,
            "role": "authenticated",
            "iat": now,
            "exp": now + 3600,
        } | overrides
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, self.private, algorithm="ES256", headers={"kid": self.kid})


class FakeJwks:
    """What the project's JWKS endpoint would serve, and how often it was
    asked."""

    def __init__(self, *keys: SigningKey) -> None:
        self.keys = list(keys)
        self.fetches = 0

    def __call__(self) -> dict:
        self.fetches += 1
        return {"keys": [k.jwk() for k in self.keys]}

    def source(self, clock=time.monotonic) -> JwksKeys:
        return JwksKeys(self, clock=clock)


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
