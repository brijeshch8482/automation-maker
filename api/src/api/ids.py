"""ULID-style ids: 48-bit millisecond time + 80 random bits, Crockford base32."""

from __future__ import annotations

import secrets
import time

_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid() -> str:
    value = (int(time.time() * 1000) << 80) | secrets.randbits(80)
    chars = []
    for _ in range(26):
        value, rem = divmod(value, 32)
        chars.append(_ALPHABET[rem])
    return "".join(reversed(chars))


def new_job_id() -> str:
    return f"job_{ulid()}"
