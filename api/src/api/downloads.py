"""Download links through the merge Worker (worker/, docs/ARCHITECTURE.md §8.6).

The token is base64url(payload) "." base64url(HMAC-SHA256(DOWNLOAD_TOKEN_SECRET, payload part)),
the same format worker/src/token.js checks. The payload names exactly what the Worker may
merge (Runner, layers, pack) and the app name; it expires in 15 minutes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from typing import Any

TOKEN_TTL_S = 900
RUNNER = re.compile(r"^runner/\d+\.\d+\.\d+$")
LAYER = re.compile(r"^layers/[A-Za-z0-9_.]+/[A-Za-z0-9_.+!]+$")
PACK = re.compile(
    r"^packs/(catalog/[a-z0-9]+(-[a-z0-9]+)*/\d+\.\d+\.\d+|jobs/job_[0-9A-Z]{26}/attempt-\d{1,2})$"
)
NAME = re.compile(r"^[A-Za-z0-9]{1,40}$")


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def download_token(
    secret: str,
    *,
    runner: str,
    layers: list[str],
    pack: str,
    name: str,
    now: float | None = None,
    ttl: int = TOKEN_TTL_S,
) -> str:
    if not (RUNNER.match(runner) and PACK.match(pack) and NAME.match(name)):
        raise ValueError("bad download payload")
    if not all(LAYER.match(layer) for layer in layers):
        raise ValueError("bad layer key")
    payload = {
        "runner": runner,
        "layers": list(layers),
        "pack": pack,
        "name": name,
        "exp": int((now if now is not None else time.time()) + ttl),
    }
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    mac = hmac.new(secret.encode(), body.encode(), hashlib.sha256).digest()
    return f"{body}.{_b64(mac)}"


def worker_link(base_url: str, secret: str, pack_entry: dict[str, Any]) -> str:
    """The Worker URL for a manifest's `pack` entry: {prefix, runner, layers, exe}."""
    token = download_token(
        secret,
        runner=pack_entry["runner"],
        layers=list(pack_entry.get("layers") or []),
        pack=pack_entry["prefix"],
        name=pack_entry["exe"],
    )
    return f"{base_url.rstrip('/')}/d/{token}"
