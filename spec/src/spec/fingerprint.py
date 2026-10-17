"""A spec's fingerprint: SHA-256 of its canonical JSON.

    python -m spec.fingerprint path/to/spec.json

The API sends the fingerprint of the spec the user confirmed with every Windows build, and the
build refuses a spec.json that differs (docs/ROUTINES.md §5), so a job branch can't change what
was confirmed, such as turning network access on. Formatting and key order don't matter.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def canonical_json(spec: dict[str, Any]) -> bytes:
    return json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def spec_sha256(spec: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(spec)).hexdigest()


if __name__ == "__main__":
    print(spec_sha256(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))))
