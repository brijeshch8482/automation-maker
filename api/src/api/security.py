"""Callback authentication: per-job routine tokens and the build-callback HMAC signature."""

from __future__ import annotations

import base64
import hashlib
import hmac


def callback_token(secret: str, job_id: str) -> str:
    """Per-job bearer token for /internal/routine-callback. Derived, so nothing to store."""
    digest = hmac.new(secret.encode(), f"routine-callback:{job_id}".encode(), hashlib.sha256)
    return base64.urlsafe_b64encode(digest.digest()).rstrip(b"=").decode()


def verify_callback_token(secret: str, job_id: str, token: str) -> bool:
    return hmac.compare_digest(callback_token(secret, job_id), token)


def sign_body(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_signature(secret: str, body: bytes, signature: str | None) -> bool:
    return signature is not None and hmac.compare_digest(sign_body(secret, body), signature)
