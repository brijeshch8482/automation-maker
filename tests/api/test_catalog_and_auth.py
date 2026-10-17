import time

import jwt
import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from api.app import create_app
from api.dispatch import FakeDispatcher
from api.providers.fake import FakeProvider

pytestmark = pytest.mark.anyio


async def test_list_automations(ctx):
    r = await ctx.client.get("/automations")
    assert r.status_code == 200
    invoice = next(a for a in r.json() if a["id"] == "invoice-generator")
    assert invoice["title"] == "Invoice Generator"
    assert invoice["network"] == {"required": False, "domains": []}
    assert invoice["description"]


async def test_get_automation(ctx):
    r = await ctx.client.get("/automations/invoice-generator")
    assert r.status_code == 200
    assert r.json()["sample_data"]["customer_name"] == "Asha Traders"
    assert (await ctx.client.get("/automations/nope")).status_code == 404


async def test_download_not_available_yet(ctx):
    r = await ctx.client.post("/automations/invoice-generator/download")
    assert r.status_code == 503
    assert (await ctx.client.post("/automations/nope/download")).status_code == 404


async def test_health(ctx):
    assert (await ctx.client.get("/health")).json() == {"status": "ok"}


async def test_jobs_need_login(ctx):
    r = await ctx.client.post("/jobs", json={"description": "Merge my PDF files monthly"})
    assert r.status_code == 401
    assert (await ctx.client.get("/me/jobs")).status_code == 401
    bad = {"Authorization": "Bearer not-a-jwt"}
    assert (await ctx.client.get("/me/jobs", headers=bad)).status_code == 401


async def _client(settings, **overrides):
    app = create_app(settings.model_copy(update=overrides), FakeProvider(), FakeDispatcher())
    await app.state.db.create_all()
    return app, AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_dev_auth_is_off_by_default(settings):
    app, client = await _client(settings, dev_auth=False)
    async with client:
        r = await client.get("/me/jobs", headers={"Authorization": "Bearer dev:alice"})
    assert r.status_code == 401
    await app.state.db.dispose()


async def test_supabase_jwt(settings):
    secret = "supabase-test-secret-with-enough-length"
    app, client = await _client(settings, dev_auth=False, supabase_jwt_secret=SecretStr(secret))

    def token(**claims):
        base = {"sub": "user-123", "aud": "authenticated", "exp": int(time.time()) + 60}
        return {"Authorization": "Bearer " + jwt.encode({**base, **claims}, secret, "HS256")}

    async with client:
        assert (await client.get("/me/jobs", headers=token())).status_code == 200
        expired = token(exp=int(time.time()) - 10)
        assert (await client.get("/me/jobs", headers=expired)).status_code == 401
        assert (await client.get("/me/jobs", headers=token(aud="other"))).status_code == 401
        forged = {
            "Authorization": "Bearer "
            + jwt.encode(
                {"sub": "x", "aud": "authenticated", "exp": 2**40},
                "wrong-secret-that-is-long-enough-for-hs256",
                "HS256",
            )
        }
        assert (await client.get("/me/jobs", headers=forged)).status_code == 401
    await app.state.db.dispose()
