"""Bundles (`.mmx`, format 2): open one and verify what's in it (docs/DESKTOP_APP.md §4-5).

    GST-Report.mmx
      bundle.json                  {"format": 2, "packs": [...], "layers": [...], "licenses": [...]}
      packs/<id>-<version>.mmx     pack format 1, unchanged (engine/pack.py)
      layers/<dist>-<version>/...  + RECORD.json
      licenses/<license_id>.json   + .sig (phase 2e: the slot is read now, checked later)
      icon.ico                     optional

bundle.json is only a table of contents and isn't trusted. Trust comes from each pack's
signature, which pins its layers through `record_sha256`. A plain pack (`app.mmx`, with
manifest.json at the top) opens as a bundle with one pack and no layers.

Nothing here writes anything: engine/store.py imports what this module verified.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from engine import __version__
from engine.pack import (
    MANIFEST,
    MAX_PACK_BYTES,
    SIGNATURE,
    TAMPERED,
    PackError,
    layer_pins,
    parse_record,
    sha256,
    verify_pack_file,
)

FORMAT = 2
BUNDLE_JSON = "bundle.json"
MAX_ENTRIES = 100_000
MAX_BUNDLE_BYTES = 1_500_000_000  # uncompressed; a pandas + numpy layer set is ~150 MB
PACK_ENTRY = re.compile(r"^packs/[a-z0-9.-]+\.mmx$")
LICENSE_ENTRY = re.compile(r"^licenses/[A-Za-z0-9_-]+\.json$")
SEMVER = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
ID = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")

INCOMPLETE = "This file is incomplete. Download it again from makemyexe.com."


def parse_version(version: object) -> tuple[int, int, int] | None:
    match = SEMVER.match(version) if isinstance(version, str) else None
    return (int(match[1]), int(match[2]), int(match[3])) if match else None


@dataclass(frozen=True)
class BundlePack:
    """A pack whose signature, files, spec and app version all checked out."""

    manifest: dict[str, Any]
    manifest_bytes: bytes  # exactly as signed: the store keeps these
    signature: bytes
    files: dict[str, bytes]

    @property
    def id(self) -> str:
        return self.manifest["id"]

    @property
    def version(self) -> str:
        return self.manifest["version"]

    @property
    def size(self) -> int:
        return sum(len(d) for d in self.files.values())


@dataclass(frozen=True)
class BundleLayer:
    """A layer in the bundle whose RECORD.json matches the signed pin (files: see read)."""

    name: str
    record_bytes: bytes
    record: dict[str, str]
    members: dict[str, zipfile.ZipInfo]  # path in the layer -> zip entry

    @property
    def size(self) -> int:
        return len(self.record_bytes) + sum(i.file_size for i in self.members.values())


def check_app_version(manifest: dict[str, Any], app_version: str = __version__) -> None:
    """§8: a pack tested with 1.3.0 needs app 1.3.0 or newer (the major was checked already)."""
    tested = parse_version(manifest.get("runner", {}).get("tested_with"))
    ours = parse_version(app_version)
    if tested is None or ours is None:
        raise PackError(TAMPERED)
    if tested > ours:
        version = ".".join(map(str, tested))
        raise PackError(f"Update MakeMyEXE to {version} or newer to add this.")


def check_identity(manifest: dict[str, Any]) -> None:
    """The id and version become folder names in the store: they must be plain."""
    ident, version = manifest.get("id"), manifest.get("version")
    if not (isinstance(ident, str) and ID.match(ident) and len(ident) <= 64):
        raise PackError(TAMPERED)
    if parse_version(version) is None:
        raise PackError(TAMPERED)


class Bundle:
    """An open bundle. Use as a context manager; nothing is trusted until a method checks it."""

    def __init__(self, path: Path) -> None:
        self.path = path
        try:
            self._zip = zipfile.ZipFile(path)
        except FileNotFoundError as err:
            raise PackError(INCOMPLETE) from err
        except (OSError, zipfile.BadZipFile) as err:
            raise PackError(TAMPERED) from err
        try:
            self._entries = {i.filename: i for i in self._zip.infolist() if not i.is_dir()}
            if len(self._entries) > MAX_ENTRIES:
                raise PackError(TAMPERED)
            if sum(i.file_size for i in self._entries.values()) > MAX_BUNDLE_BYTES:
                raise PackError(TAMPERED)
            self.toc = self._read_toc()
        except BaseException:
            self._zip.close()
            raise

    def __enter__(self) -> Bundle:
        return self

    def __exit__(self, *exc: object) -> None:
        self._zip.close()

    def _read_toc(self) -> dict[str, list[str]]:
        if BUNDLE_JSON not in self._entries:
            if MANIFEST in self._entries and SIGNATURE in self._entries:
                return {"packs": [""], "layers": [], "licenses": []}  # a plain pack v1
            raise PackError(TAMPERED)
        try:
            toc = json.loads(self._read(BUNDLE_JSON, 1_000_000))
            fmt = toc["format"]
        except (ValueError, KeyError, TypeError) as err:
            raise PackError(TAMPERED) from err
        if isinstance(fmt, int) and fmt > FORMAT:
            raise PackError("This file needs a newer MakeMyEXE. Update it from makemyexe.com.")
        lists = all(
            isinstance(toc.get(k, []), list) and all(isinstance(v, str) for v in toc.get(k, []))
            for k in ("packs", "layers", "licenses")
        )
        if fmt != FORMAT or not lists:
            raise PackError(TAMPERED)
        packs, licenses = toc["packs"], toc.get("licenses", [])
        if not packs or not all(PACK_ENTRY.match(p) and p in self._entries for p in packs):
            raise PackError(TAMPERED)
        if not all(LICENSE_ENTRY.match(n) for n in licenses):
            raise PackError(TAMPERED)
        return {"packs": packs, "layers": toc.get("layers", []), "licenses": licenses}

    def _read(self, name: str, limit: int) -> bytes:
        info = self._entries[name]
        if info.file_size > limit:
            raise PackError(TAMPERED)
        try:
            return self._zip.read(info)
        except (OSError, zipfile.BadZipFile, ValueError) as err:  # bad CRC, truncated
            raise PackError(TAMPERED) from err

    def packs(
        self, trusted_keys: dict[str, bytes], app_version: str = __version__
    ) -> list[BundlePack]:
        """§5 step 2.1-2.3 for every pack: signature, file hashes, app version."""
        result = []
        for entry in self.toc["packs"]:
            if entry == "":  # a plain pack: the file itself
                if self.path.stat().st_size > MAX_PACK_BYTES:
                    raise PackError(TAMPERED)
                data = self.path.read_bytes()
            else:
                data = self._read(entry, MAX_PACK_BYTES)
            manifest, files = verify_pack_file(io.BytesIO(data), trusted_keys)
            check_identity(manifest)
            check_app_version(manifest, app_version)
            layer_pins(manifest)  # shape
            with zipfile.ZipFile(io.BytesIO(data)) as pack:
                manifest_bytes, signature = pack.read(MANIFEST), pack.read(SIGNATURE)
            result.append(BundlePack(manifest, manifest_bytes, signature, files))
        ids = [(p.id, p.version) for p in result]
        if len(set(ids)) != len(ids):
            raise PackError(TAMPERED)
        return result

    def layer(self, name: str, expected_record: str) -> BundleLayer | None:
        """§5 step 2.4: the layer from the bundle, its RECORD.json checked; None if absent."""
        prefix = f"layers/{name}/"
        record_name = prefix + "RECORD.json"
        if record_name not in self._entries:
            return None
        record_bytes = self._read(record_name, 50_000_000)
        if sha256(record_bytes) != expected_record:
            raise PackError(TAMPERED)
        record = parse_record(record_bytes)
        members = {
            n[len(prefix) :]: i
            for n, i in self._entries.items()
            if n.startswith(prefix) and n != record_name
        }
        if set(members) != set(record):
            raise PackError(TAMPERED)  # nothing unlisted, nothing missing
        layer = BundleLayer(name, record_bytes, record, members)
        for rel in record:  # every hash, before anything is written
            for _chunk in self.read_layer_file(layer, rel):
                pass
        return layer

    def read_layer_file(self, layer: BundleLayer, rel: str) -> Iterator[bytes]:
        """The file's bytes in chunks; raises PackError at the end if its hash is wrong."""
        digest = hashlib.sha256()
        try:
            with self._zip.open(layer.members[rel]) as src:
                while chunk := src.read(1 << 20):
                    digest.update(chunk)
                    yield chunk
        except (OSError, zipfile.BadZipFile, ValueError) as err:
            raise PackError(TAMPERED) from err
        if digest.hexdigest() != layer.record[rel]:
            raise PackError(TAMPERED)

    def licenses(self) -> list[tuple[bytes, bytes]]:
        """(license.json, license.sig) pairs, unchecked: phase 2e verifies them."""
        result = []
        for name in self.toc["licenses"]:
            sig = name[: -len(".json")] + ".sig"
            if name not in self._entries or sig not in self._entries:
                raise PackError(TAMPERED)
            result.append((self._read(name, 100_000), self._read(sig, 1_000)))
        return result
