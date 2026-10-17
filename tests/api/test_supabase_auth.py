"""Supabase access tokens: asymmetric keys from a JWKS (new projects), HS256 only as a fallback."""

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from api.app import create_app
from api.auth import TokenVerifier, jwks_url
from api.dispatch import FakeDispatcher
from api.providers.fake import FakeProvider

pytestmark = pytest.mark.anyio

SUPABASE_URL = "https://abcdefgh.supabase.co"
ISSUER = f"{SUPABASE_URL}/auth/v1"
LEGACY_SECRET = "legacy-jwt-secret-that-is-at-least-32-bytes"

RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
EC_KEY = ec.generate_private_key(ec.SECP256R1())
OTHER_RSA_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwk(public_key, kid: str, alg: str) -> dict:
    algorithm = jwt.algorithms.RSAAlgorithm if alg == "RS256" else jwt.algorithms.ECAlgorithm
    return {**json.loads(algorithm.to_jwk(public_key)), "kid": kid, "alg": alg, "use": "sig"}


JWKS = {
    "keys": [
        _jwk(RSA_KEY.public_key(), "rsa-key-1", "RS256"),
        _jwk(EC_KEY.public_key(), "ec-key-1", "ES256"),
    ]
}


class FakeJWKClient(jwt.PyJWKClient):
    """PyJWKClient with its caching, but the JWKS comes from memory instead of the network."""

    def __init__(self, jwks: dict | None = JWKS) -> None:
        super().__init__(jwks_url(SUPABASE_URL), cache_keys=True, lifespan=3600)
        self._jwks = jwks
        self.fetches = 0

    def fetch_data(self):
        self.fetches += 1
        if self._jwks is None:
            raise jwt.PyJWKClientConnectionError("Fail to fetch data from the url")
        if self.jwk_set_cache is not None:
            self.jwk_set_cache.put(self._jwks)
        return self._jwks


def make_token(key=RSA_KEY, alg="RS256", kid="rsa-key-1", **claims) -> str:
    now = int(time.time())
    payload = {
        "sub": "user-123",
        "aud": "authenticated",
        "iss": ISSUER,
        "iat": now,
        "exp": now + 3600,
        "role": "authenticated",
        **claims,
    }
    payload = {k: v for k, v in payload.items() if v is not None}
    headers = {"kid": kid} if kid else {}
    return jwt.encode(payload, key, algorithm=alg, headers=headers)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
async def client(settings):
    async def make(jwks_client=None, **overrides):
        s = settings.model_copy(
            update={"dev_auth": False, "supabase_url": SUPABASE_URL, **overrides}
        )
        app = create_app(s, FakeProvider(), FakeDispatcher())
        app.state.auth = TokenVerifier(
            s, jwks_client if jwks_client is not None else FakeJWKClient()
        )
        await app.state.db.create_all()
        apps.append(app)
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://test"), app

    apps = []
    yield make
    for app in apps:
        await app.state.db.dispose()


def bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def test_rs256_token_from_jwks(client):
    c, _ = await client()
    async with c:
        r = await c.post(
            "/jobs", json={"description": "Merge PDFs every month"}, headers=bearer(make_token())
        )
        assert r.status_code == 202
        mine = await c.get("/me/jobs", headers=bearer(make_token()))
        assert [j["id"] for j in mine.json()] == [r.json()["job_id"]]
        other = await c.get("/me/jobs", headers=bearer(make_token(sub="someone-else")))
        assert other.json() == []


async def test_es256_token_from_jwks(client):
    c, _ = await client()
    async with c:
        token = make_token(key=EC_KEY, alg="ES256", kid="ec-key-1")
        assert (await c.get("/me/jobs", headers=bearer(token))).status_code == 200


@pytest.mark.parametrize(
    "token",
    [
        pytest.param(make_token(aud="anon"), id="wrong audience"),
        pytest.param(make_token(iss="https://evil.supabase.co/auth/v1"), id="wrong issuer"),
        pytest.param(make_token(iss=None), id="no issuer"),
        pytest.param(make_token(exp=int(time.time()) - 120), id="expired"),
        pytest.param(make_token(sub=None), id="no subject"),
        pytest.param(make_token(kid="unknown-key"), id="unknown key id"),
        pytest.param(make_token(key=OTHER_RSA_KEY), id="signed by a key not in the JWKS"),
        pytest.param(
            make_token(key=LEGACY_SECRET, alg="HS256", kid=None), id="HS256 without legacy secret"
        ),
        pytest.param(
            jwt.encode({"sub": "x", "aud": "authenticated"}, None, algorithm="none"), id="alg none"
        ),
        pytest.param("not.a.jwt", id="garbage"),
    ],
)
async def test_rejected_tokens(client, token):
    c, _ = await client()
    async with c:
        r = await c.get("/me/jobs", headers=bearer(token))
    assert r.status_code == 401


async def test_signing_keys_are_cached(client):
    jwks = FakeJWKClient()
    c, _ = await client(jwks_client=jwks)
    async with c:
        for _ in range(3):
            assert (await c.get("/me/jobs", headers=bearer(make_token()))).status_code == 200
    assert jwks.fetches == 1


async def test_supabase_unreachable_is_a_503_not_a_logout(client):
    c, _ = await client(jwks_client=FakeJWKClient(jwks=None))
    async with c:
        r = await c.get("/me/jobs", headers=bearer(make_token()))
    assert r.status_code == 503


async def test_legacy_hs256_fallback(client):
    c, _ = await client(supabase_jwt_secret=SecretStr(LEGACY_SECRET))
    async with c:
        legacy = make_token(key=LEGACY_SECRET, alg="HS256", kid=None)
        assert (await c.get("/me/jobs", headers=bearer(legacy))).status_code == 200
        forged = make_token(key="another-secret-that-is-at-least-32-bytes!", alg="HS256", kid=None)
        assert (await c.get("/me/jobs", headers=bearer(forged))).status_code == 401
        # Asymmetric tokens keep working alongside the legacy secret.
        assert (await c.get("/me/jobs", headers=bearer(make_token()))).status_code == 200


async def test_without_supabase_login_is_not_configured(settings):
    s = settings.model_copy(update={"dev_auth": False})
    app = create_app(s, FakeProvider(), FakeDispatcher())
    await app.state.db.create_all()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.get("/me/jobs", headers=bearer(make_token()))
    assert r.status_code == 401
    assert r.json()["detail"] == "login is not configured"
    await app.state.db.dispose()


def test_jwks_url():
    assert jwks_url(SUPABASE_URL) == "https://abcdefgh.supabase.co/auth/v1/.well-known/jwks.json"
