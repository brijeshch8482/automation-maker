"""Download links: SigV4 presigning, the catalog manifest in R2, and links on ready jobs."""

import base64
import hashlib
import hmac
import json
import time
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from api.storage import MANIFEST_KEY, Storage, presign_url

pytestmark = pytest.mark.anyio

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
MANIFEST = {
    "automations": {
        "make-pdf": {
            "version": "1.0.0",
            "exe": "MakePDF",
            "zip": "catalog/make-pdf/1.0.0/MakePDF.zip",
            "zip_bytes": 51_200_000,
            "guide": "catalog/make-pdf/1.0.0/Guide.pdf",
            "guide_bytes": 900_000,
            "built_at": "2026-10-17T11:00:00Z",
        }
    }
}


def test_presign_matches_the_aws_example():
    # docs.aws.amazon.com: "Authenticating Requests: Using Query Parameters", example GET.
    url = presign_url(
        host="examplebucket.s3.amazonaws.com",
        path="/test.txt",
        access_key="AKIAIOSFODNN7EXAMPLE",
        secret_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        region="us-east-1",
        expires=86400,
        now=datetime(2013, 5, 24, tzinfo=UTC),
    )
    assert url.endswith(
        "X-Amz-Signature=aeeed9bbccd4d02ee5c0109b86d86835f995330da4c265957d157751f604d404"
    )


def make_storage(handler) -> tuple[Storage, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def record(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return handler(request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(record))
    storage = Storage(
        account_id="acct",
        access_key_id="key-id",
        secret_access_key="secret",
        bucket="makemyexe-builds",
        client=client,
        clock=lambda: NOW,
    )
    return storage, seen


def test_links_are_signed_r2_urls_that_save_under_a_name():
    storage, _ = make_storage(lambda r: httpx.Response(200))
    link = storage.link("catalog/make-pdf/1.0.0/MakePDF.zip", filename="MakePDF.zip")
    url = urlparse(link.url)
    query = parse_qs(url.query)
    assert url.netloc == "acct.r2.cloudflarestorage.com"
    assert url.path == "/makemyexe-builds/catalog/make-pdf/1.0.0/MakePDF.zip"
    assert query["X-Amz-Expires"] == ["900"]
    assert query["X-Amz-Credential"] == ["key-id/20261017/auto/s3/aws4_request"]
    assert query["response-content-disposition"] == ['attachment; filename="MakePDF.zip"']
    assert len(query["X-Amz-Signature"][0]) == 64
    guide = storage.link("x/Guide.pdf", filename="Guide.pdf", inline=True)
    assert "inline" in parse_qs(urlparse(guide.url).query)["response-content-disposition"][0]


async def test_manifest_is_read_once_and_cached():
    storage, seen = make_storage(lambda r: httpx.Response(200, json=MANIFEST))
    assert (await storage.catalog_manifest())["make-pdf"]["exe"] == "MakePDF"
    assert (await storage.catalog_manifest())["make-pdf"]["version"] == "1.0.0"
    assert len(seen) == 1
    assert seen[0].url.path == f"/makemyexe-builds/{MANIFEST_KEY}"
    assert "X-Amz-Signature" in str(seen[0].url)


async def test_manifest_missing_or_unreachable():
    storage, _ = make_storage(lambda r: httpx.Response(404))
    assert await storage.catalog_manifest() == {}

    def boom(request):
        raise httpx.ConnectError("down")

    storage, _ = make_storage(boom)
    assert await storage.catalog_manifest() == {}
    storage, _ = make_storage(lambda r: httpx.Response(200, text="not json"))
    assert await storage.catalog_manifest() == {}


async def test_catalog_download_endpoint(ctx):
    storage, _ = make_storage(lambda r: httpx.Response(200, json=MANIFEST))
    ctx.app.state.storage = storage
    r = await ctx.client.get("/automations/make-pdf/download")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["version"] == "1.0.0"
    assert body["filename"] == "MakePDF.zip"
    assert body["size_bytes"] == 51_200_000
    assert body["expires_in"] == 900
    assert "/catalog/make-pdf/1.0.0/MakePDF.zip?" in body["url"]
    assert "/catalog/make-pdf/1.0.0/Guide.pdf?" in body["guide_url"]
    # Published automations only; no login needed.
    assert (await ctx.client.get("/automations/pdf-merge/download")).status_code == 503
    assert (await ctx.client.get("/automations/nope/download")).status_code == 404


async def test_ready_job_gets_download_links(ctx):
    job_id = await ctx.create_job()
    await ctx.to_building(job_id)
    assert (await ctx.get_job(job_id))["download_url"] is None
    r = await ctx.build_callback(
        job_id=job_id,
        attempt=0,
        status="passed",
        run_url="https://github.com/x/automation-builds/actions/runs/1",
        artifact_key=f"jobs/{job_id}/attempt-0/InvoiceGenerator.zip",
        guide_key=f"jobs/{job_id}/attempt-0/Guide.pdf",
        report=None,
    )
    assert r.status_code == 204
    assert (await ctx.get_job(job_id))["download_url"] is None  # no storage configured

    storage, _ = make_storage(lambda r: httpx.Response(200))
    ctx.app.state.storage = storage
    job = await ctx.get_job(job_id)
    assert f"/jobs/{job_id}/attempt-0/InvoiceGenerator.zip?" in job["download_url"]
    assert "filename%3D%22InvoiceGenerator.zip%22" in job["download_url"]
    assert f"/jobs/{job_id}/attempt-0/Guide.pdf?" in job["guide_url"]


# --- Downloads merged by the Worker (Phase 2b) ----------------------------------------------

PACK_ENTRY = {
    "prefix": "packs/catalog/make-pdf/1.0.0",
    "runner": "runner/1.0.0",
    "layers": [],
    "exe": "MakePDF",
    "size_bytes": 52_400_000,
}


async def test_pack_downloads_go_through_the_worker_once_configured(ctx, monkeypatch):
    from pydantic import SecretStr

    manifest = {
        "automations": {"make-pdf": {**MANIFEST["automations"]["make-pdf"], "pack": PACK_ENTRY}}
    }
    storage, _ = make_storage(lambda r: httpx.Response(200, json=manifest))
    ctx.app.state.storage = storage

    # Not configured yet: the presigned zip, as before.
    body = (await ctx.client.get("/automations/make-pdf/download")).json()
    assert "/catalog/make-pdf/1.0.0/MakePDF.zip?" in body["url"]

    settings = ctx.app.state.settings
    monkeypatch.setattr(settings, "download_worker_url", "https://dl.example.workers.dev/")
    monkeypatch.setattr(settings, "download_token_secret", SecretStr("s3cret"))
    body = (await ctx.client.get("/automations/make-pdf/download")).json()
    assert body["url"].startswith("https://dl.example.workers.dev/d/")
    assert body["filename"] == "MakePDF.zip"
    assert body["size_bytes"] == 52_400_000
    assert body["expires_in"] == 900
    assert "/packs/catalog/make-pdf/1.0.0/Guide.pdf?" in body["guide_url"]
    token = body["url"].rsplit("/", 1)[1]
    body_part, mac = token.split(".")
    payload = json.loads(base64.urlsafe_b64decode(body_part + "=" * (-len(body_part) % 4)))
    assert {k: payload[k] for k in ("runner", "layers", "pack", "name")} == {
        "runner": "runner/1.0.0",
        "layers": [],
        "pack": "packs/catalog/make-pdf/1.0.0",
        "name": "MakePDF",
    }
    assert 0 < payload["exp"] - time.time() <= 900
    signed = hmac.new(b"s3cret", body_part.encode(), hashlib.sha256).digest()
    assert base64.urlsafe_b64encode(signed).rstrip(b"=").decode() == mac


def test_tokens_name_only_known_prefixes():
    from api.downloads import download_token

    good = {"runner": "runner/1.0.0", "layers": [], "pack": PACK_ENTRY["prefix"], "name": "A"}
    download_token("s", **good)
    for bad in (
        {"runner": "runner/../x"},
        {"pack": "catalog/manifest.json"},
        {"name": "Make PDF"},
        {"layers": ["layers/../../x/1"]},
    ):
        with pytest.raises(ValueError):
            download_token("s", **{**good, **bad})


def test_r2_account_id_also_accepts_the_endpoint_url():
    from api.config import Settings
    from build.publish import r2_account_id

    bare = "0123456789abcdef0123456789abcdef"  # obviously fake
    for value in (
        bare,
        f" {bare} ",
        f"https://{bare}.r2.cloudflarestorage.com",
        f"https://{bare}.r2.cloudflarestorage.com/",
        f"{bare}.r2.cloudflarestorage.com",
        bare.upper(),
    ):
        assert r2_account_id(value) == bare, value
        assert Settings(_env_file=None, r2_account_id=value).r2_account_id == bare, value


# --- The installed app: bundles and the installer (Phase 2d) -----------------------------------


async def test_bundle_endpoint_streams_the_pack_as_mmx(ctx, monkeypatch):
    from pydantic import SecretStr

    pack = {**PACK_ENTRY, "bundle_bytes": 61_000}
    manifest = {"automations": {"make-pdf": {**MANIFEST["automations"]["make-pdf"], "pack": pack}}}
    storage, _ = make_storage(lambda r: httpx.Response(200, json=manifest))
    ctx.app.state.storage = storage
    # Not until the Worker is configured.
    assert (await ctx.client.get("/automations/make-pdf/bundle")).status_code == 503

    settings = ctx.app.state.settings
    monkeypatch.setattr(settings, "download_worker_url", "https://dl.example.workers.dev")
    monkeypatch.setattr(settings, "download_token_secret", SecretStr("s3cret"))
    body = (await ctx.client.get("/automations/make-pdf/bundle")).json()
    assert body["filename"] == "MakePDF.mmx" and body["size_bytes"] == 61_000
    token = body["url"].removeprefix("https://dl.example.workers.dev/d/")
    body_part = token.split(".")[0]
    payload = json.loads(base64.urlsafe_b64decode(body_part + "=" * (-len(body_part) % 4)))
    assert payload["kind"] == "bundle" and "runner" not in payload
    assert (payload["pack"], payload["layers"]) == ("packs/catalog/make-pdf/1.0.0", [])
    assert (await ctx.client.get("/automations/nope/bundle")).status_code == 404
    assert (await ctx.client.get("/automations/pdf-merge/bundle")).status_code == 503


async def test_bundle_needs_a_published_bundle_block(ctx, monkeypatch):
    from pydantic import SecretStr

    manifest = {
        "automations": {"make-pdf": {**MANIFEST["automations"]["make-pdf"], "pack": PACK_ENTRY}}
    }
    storage, _ = make_storage(lambda r: httpx.Response(200, json=manifest))
    ctx.app.state.storage = storage
    settings = ctx.app.state.settings
    monkeypatch.setattr(settings, "download_worker_url", "https://dl.example.workers.dev")
    monkeypatch.setattr(settings, "download_token_secret", SecretStr("s3cret"))
    # Published before bundles existed (no bundle_bytes): not offered.
    assert (await ctx.client.get("/automations/make-pdf/bundle")).status_code == 503


LATEST = {
    "version": "1.0.0",
    "key": "app/1.0.0/MakeMyEXE-Setup-1.0.0.exe",
    "size_bytes": 36_000_000,
    "sha256": "ab" * 32,
}


async def test_latest_app_is_a_signed_link_to_the_installer(ctx):
    assert (await ctx.client.get("/app/latest")).status_code == 503  # no storage

    def handler(request):
        if request.url.path.endswith("/app/latest.json"):
            return httpx.Response(200, json=LATEST)
        return httpx.Response(404)

    storage, seen = make_storage(handler)
    ctx.app.state.storage = storage
    body = (await ctx.client.get("/app/latest")).json()
    assert body["version"] == "1.0.0" and body["filename"] == "MakeMyEXE-Setup-1.0.0.exe"
    assert body["size_bytes"] == 36_000_000 and body["sha256"] == "ab" * 32
    assert "/app/1.0.0/MakeMyEXE-Setup-1.0.0.exe?" in body["url"]
    assert body["expires_in"] == 900
    await ctx.client.get("/app/latest")
    assert len(seen) == 1  # cached


async def test_latest_app_before_a_release_or_with_a_bad_pointer():
    storage, _ = make_storage(lambda r: httpx.Response(404))
    assert await storage.app_latest() is None
    storage, _ = make_storage(lambda r: httpx.Response(200, json={**LATEST, "key": "../x"}))
    assert await storage.app_latest() is None


async def test_ready_custom_app_with_a_pack_offers_add_to_makemyexe(ctx, monkeypatch):
    from pydantic import SecretStr

    from tests.api.conftest import ALICE, BOB

    job_id = await ctx.create_job()
    await ctx.to_building(job_id)
    prefix = f"packs/jobs/{job_id}/attempt-0"
    r = await ctx.build_callback(
        job_id=job_id,
        attempt=0,
        status="passed",
        run_url="https://github.com/x/automation-builds/actions/runs/1",
        artifact_key=f"jobs/{job_id}/attempt-0/InvoiceGenerator.zip",
        guide_key=f"jobs/{job_id}/attempt-0/Guide.pdf",
        report=None,
        pack={"prefix": prefix, "exe": "InvoiceGenerator", "layers": [], "bundle_bytes": 4321},
    )
    assert r.status_code == 204
    job = await ctx.get_job(job_id)
    assert job["bundle_available"] is True
    # Not yet configured: no link.
    url = f"/jobs/{job_id}/bundle"
    assert (await ctx.client.get(url, headers=ALICE)).status_code == 503

    storage, _ = make_storage(lambda r: httpx.Response(200))
    ctx.app.state.storage = storage
    settings = ctx.app.state.settings
    monkeypatch.setattr(settings, "download_worker_url", "https://dl.example.workers.dev")
    monkeypatch.setattr(settings, "download_token_secret", SecretStr("s3cret"))
    body = (await ctx.client.get(url, headers=ALICE)).json()
    assert body["filename"] == "InvoiceGenerator.mmx" and body["size_bytes"] == 4321
    token = body["url"].removeprefix("https://dl.example.workers.dev/d/")
    part = token.split(".")[0]
    payload = json.loads(base64.urlsafe_b64decode(part + "=" * (-len(part) % 4)))
    assert (payload["kind"], payload["pack"]) == ("bundle", prefix)
    assert f"/jobs/{job_id}/attempt-0/Guide.pdf?" in body["guide_url"]
    # Someone else's job: not found, like every other job route.
    assert (await ctx.client.get(url, headers=BOB)).status_code == 404


async def test_a_pack_named_for_another_job_is_ignored(ctx):
    job_id = await ctx.create_job()
    await ctx.to_building(job_id)
    r = await ctx.build_callback(
        job_id=job_id,
        attempt=0,
        status="passed",
        run_url=None,
        artifact_key=f"jobs/{job_id}/attempt-0/App.zip",
        guide_key=None,
        report=None,
        pack={
            "prefix": "packs/jobs/job_01OTHEROTHEROTHEROTHEROTHE/attempt-0",
            "exe": "App",
            "bundle_bytes": 10,
        },
    )
    assert r.status_code == 204
    assert (await ctx.get_job(job_id))["bundle_available"] is False
