"""Finished apps in Cloudflare R2 (private bucket) and short-lived download links to them.

R2 speaks the S3 API. Links are presigned with AWS Signature V4 (query string), implemented here
with the standard library so the API needs no AWS SDK. Give the API a **read-only** R2 token:
it only signs GET links and reads the catalog manifest; uploads happen in GitHub Actions.

Layout in the bucket:
    catalog/manifest.json                      written by build/publish_catalog.py
    catalog/<id>/<version>/<Exe>.zip, Guide.pdf
    jobs/<job_id>/attempt-<n>/<Exe>.zip, Guide.pdf   written by automation-builds Job 2
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

log = logging.getLogger(__name__)

MANIFEST_KEY = "catalog/manifest.json"
APP_LATEST_KEY = "app/latest.json"  # written by build/installer.py publish
MANIFEST_TTL_S = 300  # a new release shows up within five minutes
LINK_TTL_S = 900


def _quote(value: str, safe: str = "-_.~") -> str:
    return quote(value, safe=safe)


def _hmac(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode(), hashlib.sha256).digest()


def presign_url(
    *,
    host: str,
    path: str,
    access_key: str,
    secret_key: str,
    region: str,
    expires: int,
    now: datetime,
    method: str = "GET",
    params: dict[str, str] | None = None,
    service: str = "s3",
) -> str:
    """An AWS SigV4 presigned URL (query-string auth, payload unsigned)."""
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    datestamp = now.strftime("%Y%m%d")
    scope = f"{datestamp}/{region}/{service}/aws4_request"
    query = {
        "X-Amz-Algorithm": "AWS4-HMAC-SHA256",
        "X-Amz-Credential": f"{access_key}/{scope}",
        "X-Amz-Date": amz_date,
        "X-Amz-Expires": str(expires),
        "X-Amz-SignedHeaders": "host",
        **(params or {}),
    }
    canonical_query = "&".join(f"{_quote(k)}={_quote(v)}" for k, v in sorted(query.items()))
    canonical_uri = _quote(path, safe="/-_.~")
    canonical_request = "\n".join(
        [method, canonical_uri, canonical_query, f"host:{host}\n", "host", "UNSIGNED-PAYLOAD"]
    )
    string_to_sign = "\n".join(
        [
            "AWS4-HMAC-SHA256",
            amz_date,
            scope,
            hashlib.sha256(canonical_request.encode()).hexdigest(),
        ]
    )
    key = _hmac(("AWS4" + secret_key).encode(), datestamp)
    for part in (region, service, "aws4_request"):
        key = _hmac(key, part)
    signature = hmac.new(key, string_to_sign.encode(), hashlib.sha256).hexdigest()
    return f"https://{host}{canonical_uri}?{canonical_query}&X-Amz-Signature={signature}"


@dataclass(frozen=True)
class Link:
    url: str
    expires_in: int


class Storage:
    """Signs links into the bucket and reads the catalog manifest (cached)."""

    def __init__(
        self,
        *,
        account_id: str,
        access_key_id: str,
        secret_access_key: str,
        bucket: str,
        client: httpx.AsyncClient | None = None,
        clock: Any = None,
    ) -> None:
        self._host = f"{account_id}.r2.cloudflarestorage.com"
        self._access_key = access_key_id
        self._secret = secret_access_key
        self._bucket = bucket
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._cache: dict[str, tuple[float, dict[str, Any] | None]] = {}

    def link(self, key: str, *, filename: str, inline: bool = False, ttl: int = LINK_TTL_S) -> Link:
        """A GET link that saves the file as `filename` (or shows it, for the guide)."""
        disposition = "inline" if inline else "attachment"
        url = presign_url(
            host=self._host,
            path=f"/{self._bucket}/{key}",
            access_key=self._access_key,
            secret_key=self._secret,
            region="auto",
            expires=ttl,
            now=self._clock(),
            params={"response-content-disposition": f'{disposition}; filename="{filename}"'},
        )
        return Link(url, ttl)

    async def catalog_manifest(self) -> dict[str, Any]:
        """{automation id: entry}; empty when nothing is published or R2 can't be read."""
        data = await self._cached_json(MANIFEST_KEY)
        return dict(data.get("automations", {})) if data else {}

    async def app_latest(self) -> dict[str, Any] | None:
        """The installer pointer app/latest.json (docs/DEPLOY.md §12); None until a release."""
        data = await self._cached_json(APP_LATEST_KEY)
        if not data or not isinstance(data.get("key"), str) or not data["key"].startswith("app/"):
            return None
        return data

    async def _cached_json(self, key: str) -> dict[str, Any] | None:
        """A small JSON object from the bucket, cached a few minutes. None if missing or
        unreadable; on a network error the last good copy is kept."""
        cached = self._cache.get(key)
        if cached is not None and time.monotonic() - cached[0] < MANIFEST_TTL_S:
            return cached[1]
        url = presign_url(
            host=self._host,
            path=f"/{self._bucket}/{key}",
            access_key=self._access_key,
            secret_key=self._secret,
            region="auto",
            expires=60,
            now=self._clock(),
        )
        try:
            response = await self._client.get(url)
        except httpx.HTTPError as err:
            log.warning("%s unreachable: %r", key, err)
            return cached[1] if cached else None
        data: dict[str, Any] | None
        if response.status_code == 404:
            data = None
        elif response.is_success:
            try:
                parsed = response.json()
                data = parsed if isinstance(parsed, dict) else None
            except ValueError:
                log.warning("%s is not valid JSON", key)
                data = None
        else:
            log.warning("%s: R2 returned %s", key, response.status_code)
            return cached[1] if cached else None
        self._cache[key] = (time.monotonic(), data)
        return data


def make_storage(settings: Any) -> Storage | None:
    values = (
        settings.r2_account_id,
        settings.r2_access_key_id,
        settings.r2_secret_access_key.get_secret_value(),
        settings.r2_bucket,
    )
    if not all(values):
        return None
    account_id, access_key_id, secret, bucket = values
    return Storage(
        account_id=account_id, access_key_id=access_key_id, secret_access_key=secret, bucket=bucket
    )
