"""Make and sign an app pack (`app.mmx`, docs/ARCHITECTURE.md §8.2-8.3).

    python -m build.pack make <app_dir> --out <dir> --kind catalog|job --key-id ID
        [--expect-spec-sha256 HEX] [--runner-version V]     key PEM in env PACK_SIGNING_KEY
    python -m build.pack keygen --key-id ID --out <dir>      a new key pair (docs/DEPLOY.md §9)

Runs only in trusted publish jobs, which never run generated code: it reads the app folder as
data (from the pinned commit, never from a build artifact), lists every file with its sha256
in manifest.json, signs the exact manifest bytes with Ed25519 through `openssl pkeyutl`, and
writes a zip the Runner verifies before it loads anything (engine/pack.py). Standard library
and the openssl CLI only.

A pack holds spec.json, optional custom_step.py, samples/ (fake files for the smoke test) and
assets/. Never tests, caches, or anything with user data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

FORMAT = 1
RUNNER_MAJOR = 1
KINDS = ("catalog", "job")
# Same as engine/pack.py ALLOWED_FILE (a test keeps them equal).
ALLOWED_FILE = re.compile(r"^(spec\.json|custom_step\.py|(samples|assets)/[^\\:*?\"<>|]+)$")
KEY_ID = re.compile(r"^[a-z0-9-]{1,32}$")
MAX_FILES = 200
MAX_PACK_BYTES = 60_000_000
ZIP_TIME = (2020, 1, 1, 0, 0, 0)  # fixed, so the same files give the same pack bytes
REPO_ROOT = Path(__file__).resolve().parent.parent


class PackError(Exception):
    pass


def spec_sha256(spec: dict[str, Any]) -> str:
    """Same as spec.fingerprint.spec_sha256 (a test keeps them equal)."""
    canonical = json.dumps(spec, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


def collect(app_dir: Path) -> dict[str, bytes]:
    """The pack's files from an automation or job folder, by pack path."""
    files: dict[str, bytes] = {}
    for name in ("spec.json", "custom_step.py"):
        path = app_dir / name
        if path.is_symlink():
            raise PackError(f"{name} is a link")
        if path.is_file():
            files[name] = path.read_bytes()
    if "spec.json" not in files:
        raise PackError("spec.json is missing")
    for folder in ("samples", "assets"):
        for path in sorted((app_dir / folder).rglob("*")):
            rel = path.relative_to(app_dir).as_posix()
            if "__pycache__" in path.parts:
                continue
            if path.is_symlink():
                raise PackError(f"{rel} is a link")
            if path.is_file():
                files[rel] = path.read_bytes()
    for name in files:
        if not ALLOWED_FILE.match(name) or ".." in name.split("/"):
            raise PackError(f"{name} may not be in a pack")
    if len(files) > MAX_FILES or sum(map(len, files.values())) > MAX_PACK_BYTES:
        raise PackError("the app folder is too big for a pack")
    return files


def make_manifest(
    files: dict[str, bytes],
    kind: str,
    key_id: str,
    runner_version: str,
    layers: list[dict[str, str]] | None = None,
    now: datetime | None = None,
) -> bytes:
    if kind not in KINDS:
        raise PackError(f"kind must be one of {', '.join(KINDS)}")
    if not KEY_ID.match(key_id):
        raise PackError("key id must be lower-case letters, digits and '-'")
    try:
        spec = json.loads(files["spec.json"])
        ident, version, title = spec["id"], spec["version"], spec["title"]
    except (ValueError, KeyError, TypeError) as err:
        raise PackError("spec.json has no id, version and title") from err
    network = spec.get("network") or {}
    manifest = {
        "format": FORMAT,
        "id": ident,
        "version": version,
        "title": title,
        "kind": kind,
        "runner": {"major": RUNNER_MAJOR, "tested_with": runner_version},
        "network": {
            "required": bool(network.get("required")),
            "domains": list(network.get("domains") or []),
        },
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
        "layers": layers or [],
        "key_id": key_id,
        "created_at": (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return json.dumps(manifest, indent=2, sort_keys=True).encode() + b"\n"


def openssl_sign(private_key_pem: str, message: bytes) -> bytes:
    """Ed25519 signature of `message`; the key only ever touches a 0600 temp file."""
    with tempfile.TemporaryDirectory(prefix="makemyexe-sign-") as tmp:
        key, msg, sig = Path(tmp, "key.pem"), Path(tmp, "manifest.json"), Path(tmp, "sig")
        fd = os.open(key, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(private_key_pem)
        msg.write_bytes(message)
        cmd = ["openssl", "pkeyutl", "-sign", "-inkey", str(key), "-rawin"]
        result = subprocess.run(
            [*cmd, "-in", str(msg), "-out", str(sig)], capture_output=True, text=True, check=False
        )
        if result.returncode != 0:
            # openssl's message names the file, never the key contents.
            raise PackError(f"signing failed: {result.stderr.strip()[-300:]}")
        signature = sig.read_bytes()
    if len(signature) != 64:
        raise PackError("signing did not produce an Ed25519 signature")
    return signature


def write_pack(target: Path, manifest: bytes, signature: bytes, files: dict[str, bytes]) -> Path:
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        entries = [("manifest.json", manifest), ("manifest.sig", signature), *sorted(files.items())]
        for name, data in entries:
            archive.writestr(zipfile.ZipInfo(name, ZIP_TIME), data, zipfile.ZIP_DEFLATED)
    return target


def make_pack(
    app_dir: Path,
    out: Path,
    kind: str,
    key_id: str,
    private_key_pem: str,
    runner_version: str,
    expect_spec_sha256: str | None = None,
    layers: list[dict[str, str]] | None = None,
) -> Path:
    files = collect(app_dir)
    confirmed = expect_spec_sha256 and expect_spec_sha256.lower()
    if confirmed and spec_sha256(json.loads(files["spec.json"])) != confirmed:
        raise PackError("spec.json is not the spec the user confirmed")
    manifest = make_manifest(files, kind, key_id, runner_version, layers)
    return write_pack(out / "app.mmx", manifest, openssl_sign(private_key_pem, manifest), files)


def keygen(key_id: str, out: Path) -> tuple[Path, str]:
    """A new Ed25519 key pair: <out>/<key_id>.pem (private) and the public key as hex."""
    if not KEY_ID.match(key_id):
        raise PackError("key id must be lower-case letters, digits and '-'")
    out.mkdir(parents=True, exist_ok=True)
    private = out / f"{key_id}.pem"
    if private.exists():
        raise PackError(f"{private} already exists")
    subprocess.run(
        ["openssl", "genpkey", "-algorithm", "ed25519", "-out", str(private)],
        check=True,
        capture_output=True,
    )
    os.chmod(private, 0o600)
    der = subprocess.run(
        ["openssl", "pkey", "-in", str(private), "-pubout", "-outform", "DER"],
        check=True,
        capture_output=True,
    ).stdout
    return private, der[-32:].hex()


def engine_version() -> str:
    """The Runner version a pack is tested with (x.y.z): the engine release automation-builds
    was synced from (ENGINE_VERSION, "engine-v1.0.0 <commit>"), else engine/pyproject.toml."""
    marker = REPO_ROOT / "ENGINE_VERSION"
    if marker.is_file():
        text = marker.read_text(encoding="utf-8")
    else:
        project = REPO_ROOT / "engine" / "pyproject.toml"
        found = re.search(
            r'^version = "([^"]+)"',
            project.read_text(encoding="utf-8") if project.is_file() else "",
            re.M,
        )
        text = found.group(1) if found else ""
    match = re.search(r"\d+\.\d+\.\d+", text)
    return match.group(0) if match else "dev"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m build.pack", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    make = sub.add_parser("make", help="make and sign app.mmx")
    make.add_argument("app_dir", type=Path)
    make.add_argument("--out", type=Path, required=True)
    make.add_argument("--kind", choices=KINDS, required=True)
    make.add_argument("--key-id", required=True)
    make.add_argument("--expect-spec-sha256", metavar="HEX")
    make.add_argument("--runner-version", default=engine_version())
    gen = sub.add_parser("keygen", help="make a new signing key pair")
    gen.add_argument("--key-id", required=True)
    gen.add_argument("--out", type=Path, required=True)
    gen.add_argument("--public-out", type=Path, help="also write {key_id: public hex} here")
    args = parser.parse_args(argv)

    try:
        if args.command == "keygen":
            private, public = keygen(args.key_id, args.out)
            if args.public_out:
                args.public_out.write_text(json.dumps({args.key_id: public}), encoding="utf-8")
            print(f"private key: {private}  (paste into the GitHub environment, then delete)")
            print(f'public key:  "{args.key_id}": "{public}"  (add to build/trusted_keys.json)')
            return 0
        key = os.environ.get("PACK_SIGNING_KEY", "")
        if not key.strip():
            raise PackError("PACK_SIGNING_KEY is not set")
        pack = make_pack(
            args.app_dir,
            args.out,
            args.kind,
            args.key_id,
            key,
            args.runner_version,
            args.expect_spec_sha256,
        )
    except PackError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print(f"{pack} ({pack.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
