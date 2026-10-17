"""App packs (`app.mmx`): open, verify, unpack (docs/ARCHITECTURE.md §8.2-8.3).

A pack is a zip of manifest.json, manifest.sig (64-byte Ed25519 signature over the exact bytes
of manifest.json) and the files the manifest lists with their sha256: spec.json, optional
custom_step.py, samples/ and assets/. Before anything from a pack is used:

1. the signature is checked with the trusted key named by `key_id`;
2. the zip holds exactly the listed files, each with the listed hash;
3. spec.json matches the manifest's id and version, and the pack's Runner major is ours;
4. every layer the manifest pins (libs/<dist>-<version>/ next to the exe) matches its
   RECORD.json, and RECORD.json matches the manifest; nothing unlisted is in a layer folder.

Any mismatch raises PackError and nothing runs. Verification is offline. Packs are made and
signed only by build/pack.py in the publish jobs.
"""

from __future__ import annotations

import atexit
import hashlib
import json
import re
import shutil
import sys
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from engine import ed25519
from engine.errors import EngineError

if TYPE_CHECKING:
    from engine.loader import LoadedSpec

PACK_NAME = "app.mmx"
MANIFEST, SIGNATURE = "manifest.json", "manifest.sig"
FORMAT = 1
RUNNER_MAJOR = 1
KINDS = ("catalog", "job")
ALLOWED_FILE = re.compile(r"^(spec\.json|custom_step\.py|(samples|assets)/[^\\:*?\"<>|]+)$")
MAX_FILES = 200
MAX_PACK_BYTES = 60_000_000  # uncompressed; packs are KB, samples a few MB
LAYER_NAME = re.compile(r"^[A-Za-z0-9_.]+-[A-Za-z0-9_.+!]+$")

TAMPERED = "This app was changed after MakeMyEXE made it. Download it again from makemyexe.com."


class PackError(EngineError):
    """The pack can't be trusted. The message is safe to show and holds no user data."""


@dataclass(frozen=True)
class VerifiedPack:
    manifest: dict[str, Any]
    files: dict[str, bytes]  # path -> contents, every hash checked
    layer_dirs: list[Path]  # verified libs/<dist>-<version>/ folders, for sys.path

    def unpack(self, target: Path | None = None) -> Path:
        """Write the verified files into a fresh folder (temp by default) and return it."""
        root = Path(target or tempfile.mkdtemp(prefix=f"makemyexe-{self.manifest['id']}-"))
        for name, data in self.files.items():
            path = root.joinpath(*PurePosixPath(name).parts)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("xb") as fh:  # a fresh folder: never overwrite
                fh.write(data)
        return root


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verify_pack(
    pack_path: Path, trusted_keys: dict[str, bytes], app_dir: Path | None = None
) -> VerifiedPack:
    """Open and fully verify a pack. `app_dir` holds libs/ (default: the pack's folder)."""
    try:
        archive = zipfile.ZipFile(pack_path)
    except FileNotFoundError as err:
        raise PackError("This folder is incomplete. Download the app again.") from err
    except (OSError, zipfile.BadZipFile) as err:
        raise PackError(TAMPERED) from err
    with archive:
        entries = {info.filename: info for info in archive.infolist() if not info.is_dir()}
        if MANIFEST not in entries or SIGNATURE not in entries:
            raise PackError(TAMPERED)
        if len(entries) > MAX_FILES + 2:
            raise PackError(TAMPERED)
        if sum(info.file_size for info in entries.values()) > MAX_PACK_BYTES:
            raise PackError(TAMPERED)
        manifest_bytes = archive.read(MANIFEST)
        signature = archive.read(SIGNATURE)
        manifest = _check_signature(manifest_bytes, signature, trusted_keys)
        listed: dict[str, str] = manifest["files"]
        if set(entries) != set(listed) | {MANIFEST, SIGNATURE}:
            raise PackError(TAMPERED)
        files = {}
        for name, expected in listed.items():
            data = archive.read(name)
            if sha256(data) != expected:
                raise PackError(TAMPERED)
            files[name] = data

    _check_spec(manifest, files)
    layer_dirs = verify_layers(manifest, app_dir or Path(pack_path).parent)
    return VerifiedPack(manifest, files, layer_dirs)


def _check_signature(
    manifest_bytes: bytes, signature: bytes, trusted_keys: dict[str, bytes]
) -> dict[str, Any]:
    try:
        manifest = json.loads(manifest_bytes)
        key = trusted_keys.get(manifest["key_id"])
    except (ValueError, KeyError, TypeError) as err:
        raise PackError(TAMPERED) from err
    if key is None or not ed25519.verify(key, manifest_bytes, signature):
        raise PackError(TAMPERED)
    # Signed, so these are ours; still check the shape before relying on it.
    try:
        ok = (
            manifest["format"] == FORMAT
            and manifest["kind"] in KINDS
            and isinstance(manifest["files"], dict)
            and all(ALLOWED_FILE.match(n) and ".." not in n.split("/") for n in manifest["files"])
            and isinstance(manifest["layers"], list)
        )
    except (KeyError, TypeError) as err:
        raise PackError(TAMPERED) from err
    if not ok:
        raise PackError(TAMPERED)
    if manifest.get("runner", {}).get("major") != RUNNER_MAJOR:
        raise PackError(
            "This app needs a different version of MakeMyEXE. Download it again from makemyexe.com."
        )
    return manifest


def _check_spec(manifest: dict[str, Any], files: dict[str, bytes]) -> None:
    try:
        spec = json.loads(files["spec.json"])
    except (KeyError, ValueError) as err:
        raise PackError(TAMPERED) from err
    if spec.get("id") != manifest.get("id") or spec.get("version") != manifest.get("version"):
        raise PackError(TAMPERED)


def verify_layers(manifest: dict[str, Any], app_dir: Path) -> list[Path]:
    """Check every pinned layer folder against its RECORD.json and the signed manifest."""
    dirs = []
    for layer in manifest["layers"]:
        try:
            name = f"{layer['dist']}-{layer['version']}"
            expected_record = layer["record_sha256"]
        except (KeyError, TypeError) as err:
            raise PackError(TAMPERED) from err
        if not LAYER_NAME.match(name):
            raise PackError(TAMPERED)
        folder = app_dir / "libs" / name
        record_path = folder / "RECORD.json"
        try:
            record_bytes = record_path.read_bytes()
        except OSError as err:
            raise PackError("This folder is incomplete. Download the app again.") from err
        if sha256(record_bytes) != expected_record:
            raise PackError(TAMPERED)
        try:
            record: dict[str, str] = json.loads(record_bytes)
        except ValueError as err:
            raise PackError(TAMPERED) from err
        present = {
            p.relative_to(folder).as_posix()
            for p in folder.rglob("*")
            if p.is_file() or p.is_symlink()
        } - {"RECORD.json"}
        if present != set(record):
            raise PackError(TAMPERED)
        for rel, digest in record.items():
            path = folder.joinpath(*PurePosixPath(rel).parts)
            if path.is_symlink() or sha256(path.read_bytes()) != digest:
                raise PackError(TAMPERED)
        dirs.append(folder)
    return dirs


def started_from_zip(exe: Path) -> bool:
    """Explorer runs an exe opened inside a zip from a temp copy (...\\Temp1_App.zip\\...)."""
    return any(part.lower().endswith(".zip") for part in exe.parent.parts)


def load_pack(
    pack_path: Path, trusted_keys: dict[str, bytes], app_dir: Path | None = None
) -> LoadedSpec:
    """Verify a pack, make its layers importable, unpack it, and load its spec."""
    from engine.loader import load_spec

    pack = verify_pack(pack_path, trusted_keys, app_dir)
    for folder in pack.layer_dirs:
        if str(folder) not in sys.path:
            sys.path.append(str(folder))
    unpacked = pack.unpack()
    # Our own temp copy of the pack (never user files): removed when the app closes.
    atexit.register(shutil.rmtree, unpacked, ignore_errors=True)
    return load_spec(unpacked / "spec.json")
