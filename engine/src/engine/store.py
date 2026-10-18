"""The app store on this PC: installed automations and layers (docs/DESKTOP_APP.md §3.1, §5, §6).

    %LOCALAPPDATA%\\MakeMyEXE\\          (MAKEMYEXE_STORE_DIR overrides it)
      install.json                          install_id, created_at, format
      store\\automations\\<id>\\<version>\\   manifest.json, manifest.sig + the pack's files
      store\\libs\\<dist>-<version>\\        verified layers, shared by every automation
      store\\licenses\\                      phase 2e
      store\\index.json                      installed versions and the layers each uses

Not to be confused with engine/storage.py: one automation's settings and data in %APPDATA%.

Import (§5) verifies everything in the bundle first, then writes each new layer and pack version
into a `.tmp-<random>` folder next to its place and renames it into place, then updates
index.json (written to a temp file and replaced). Run (§6) verifies the installed copy again
every time: the store is user-writable, so a check at import isn't enough. index.json is only
a list for finding things; trust always comes from the signatures. Everything removed here
(old versions, unused layers, leftovers of a failed import) is in our own store, never a user
file.
"""

from __future__ import annotations

import json
import os
import secrets
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any

from engine import __version__
from engine.bundle import (
    INCOMPLETE,
    Bundle,
    BundleLayer,
    BundlePack,
    check_app_version,
    check_identity,
    parse_version,
)
from engine.pack import (
    TAMPERED,
    PackError,
    VerifiedPack,
    layer_pins,
    load_verified,
    verify_layer,
    verify_layers,
    verify_pack_dir,
)

if TYPE_CHECKING:
    from engine.loader import LoadedSpec

STORE_DIR_ENV = "MAKEMYEXE_STORE_DIR"
INDEX_FORMAT = 1
INSTALL_FORMAT = 1
TMP_PREFIX, OLD_PREFIX = ".tmp-", ".old-"
NOT_INSTALLED = "This automation isn't installed. Add it again from makemyexe.com."


@dataclass(frozen=True)
class StoreSettings:
    """Defaults from DESKTOP_APP.md §5 and §15."""

    keep_versions: int = 2  # per automation, so the user can switch back
    # Pack kinds that need a license at import and run (§7.4). Empty in the internal phase:
    # catalog automations are free and so are custom builds (§15). Licensing comes in 2e.
    licensed_kinds: frozenset[str] = frozenset()


@dataclass
class ImportPlan:
    """What the confirmation shows (§5 step 3), one per pack in the bundle."""

    id: str
    version: str
    title: str
    kind: str
    network_domains: list[str]  # empty: works offline
    size_bytes: int  # the pack's files plus the layers this PC doesn't have yet
    installed: list[str]  # versions already here, newest first
    new_layers: list[str] = field(default_factory=list)

    @property
    def replaces(self) -> str | None:
        """The newest installed version, when this is an update or a downgrade."""
        return self.installed[0] if self.installed and self.installed[0] != self.version else None

    @property
    def downgrade(self) -> bool:
        return bool(self.installed) and _key(self.version) < _key(self.installed[0])

    @property
    def reinstall(self) -> bool:
        return self.version in self.installed


def keep_newer(plan: ImportPlan) -> bool:
    """The default answer: import, except an older version than the installed one (§5)."""
    return not plan.downgrade


@dataclass(frozen=True)
class ImportResult:
    plan: ImportPlan
    imported: bool


def default_root() -> Path:
    if override := os.environ.get(STORE_DIR_ENV):
        return Path(override)
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "MakeMyEXE"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "MakeMyEXE"


def _key(version: str) -> tuple[int, int, int]:
    return parse_version(version) or (-1, -1, -1)


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class AppStore:
    def __init__(
        self,
        root: Path | None = None,
        trusted_keys: dict[str, bytes] | None = None,
        settings: StoreSettings | None = None,
        app_version: str = __version__,
    ) -> None:
        if trusted_keys is None:
            from engine.keys import trusted_keys as load_keys

            trusted_keys = load_keys()
        self.root = root or default_root()
        self.automations_dir = self.root / "store" / "automations"
        self.libs_dir = self.root / "store" / "libs"
        self.licenses_dir = self.root / "store" / "licenses"
        self.index_path = self.root / "store" / "index.json"
        self.trusted_keys = trusted_keys
        self.settings = settings or StoreSettings()
        self.app_version = app_version

    # --- install.json and index.json ---------------------------------------------------------

    def install_id(self) -> str:
        """128 random bits, made on first use and kept (a reinstall keeps the store, §7.2)."""
        path = self.root / "install.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            value = data["install_id"]
            if isinstance(value, str) and len(bytes.fromhex(value)) == 16:
                return value
        except (OSError, ValueError, KeyError, TypeError):
            pass
        value = secrets.token_hex(16)
        info = {"format": INSTALL_FORMAT, "install_id": value, "created_at": _now()}
        self._write_json(path, info)
        return value

    def index(self) -> dict[str, Any]:
        """{id: {"selected": version | None, "versions": {version: info}}}. Rebuilt if broken."""
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
            if data.get("format") == INDEX_FORMAT and isinstance(data.get("automations"), dict):
                return data["automations"]
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, AttributeError):
            pass
        return self._rebuild_index()

    def _save_index(self, automations: dict[str, Any]) -> None:
        self._write_json(self.index_path, {"format": INDEX_FORMAT, "automations": automations})

    def _rebuild_index(self) -> dict[str, Any]:
        """From the folders on disk. Unverified, like any index: run checks the signatures."""
        automations: dict[str, Any] = {}
        for folder in sorted(self.automations_dir.glob("*/*/manifest.json")):
            try:
                manifest = json.loads(folder.read_text(encoding="utf-8"))
                check_identity(manifest)
                info = _version_info(manifest)
            except (OSError, ValueError, PackError, KeyError, TypeError):
                continue
            ident, version = folder.parent.parent.name, folder.parent.name
            if (manifest["id"], manifest["version"]) == (ident, version):
                entry = automations.setdefault(ident, {"selected": None, "versions": {}})
                entry["versions"][version] = info
        self._save_index(automations)
        return automations

    @staticmethod
    def _write_json(path: Path, data: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f"{path.name}{TMP_PREFIX}{secrets.token_hex(4)}")
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
        os.replace(tmp, path)

    def installed(self) -> dict[str, list[str]]:
        """{id: versions, newest first}."""
        return {
            ident: sorted(entry.get("versions", {}), key=_key, reverse=True)
            for ident, entry in self.index().items()
        }

    def resolve(self, automation_id: str, version: str | None = None) -> str:
        """The version to run (§6 step 2): the one asked for, the selected one, or the newest."""
        entry = self.index().get(automation_id)
        versions = sorted((entry or {}).get("versions", {}), key=_key, reverse=True)
        if not versions:
            raise PackError(NOT_INSTALLED)
        chosen = version or entry.get("selected") or versions[0]
        if chosen not in versions:
            raise PackError(NOT_INSTALLED)
        return chosen

    def select(self, automation_id: str, version: str | None) -> None:
        """Switch back to a kept version in the Hub; None goes back to the newest."""
        automations = self.index()
        entry = automations.get(automation_id)
        if entry is None or (version is not None and version not in entry["versions"]):
            raise PackError(NOT_INSTALLED)
        entry["selected"] = version
        self._save_index(automations)

    # --- import (§5) ------------------------------------------------------------------------

    def import_bundle(
        self, path: Path, confirm: Callable[[ImportPlan], bool] = keep_newer
    ) -> list[ImportResult]:
        """Verify everything in the bundle, ask, then install. Raises PackError, writes nothing,
        if anything in it fails a check."""
        with Bundle(path) as bundle:
            packs = bundle.packs(self.trusted_keys, self.app_version)  # step 2.1-2.3
            planned = []
            for pack in packs:
                layers = self._layers_for(pack, bundle)  # step 2.4
                self._check_license(pack.manifest, bundle.licenses())  # step 2.5
                planned.append((pack, layers, self._plan(pack, layers)))
            results = []
            for pack, layers, plan in planned:
                if not confirm(plan):  # step 3
                    results.append(ImportResult(plan, False))
                    continue
                for layer in layers:  # step 4
                    if layer is not None:
                        self._install_layer(bundle, layer)
                self._install_pack(pack)
                results.append(ImportResult(plan, True))
        return results

    def _layers_for(self, pack: BundlePack, bundle: Bundle) -> list[BundleLayer | None]:
        """For each pinned layer: None to reuse the store's copy, else the bundle's (verified)."""
        result: list[BundleLayer | None] = []
        for name, expected in layer_pins(pack.manifest):
            try:
                verify_layer(self.libs_dir / name, expected)
                result.append(None)
                continue
            except PackError:
                pass  # not here, or damaged: the bundle must bring it
            layer = bundle.layer(name, expected)
            if layer is None:
                raise PackError(INCOMPLETE)
            result.append(layer)
        return result

    def _check_license(self, manifest: dict[str, Any], licenses: list[tuple[bytes, bytes]]) -> None:
        """§5 step 2.5 / §6 step 3. No kind needs a license until phase 2e (settings)."""
        if manifest["kind"] in self.settings.licensed_kinds:
            raise PackError(
                "This automation is licensed to another MakeMyEXE ID. "
                "Link this PC on the website and download it again."
            )

    def _plan(self, pack: BundlePack, layers: list[BundleLayer | None]) -> ImportPlan:
        network = pack.manifest.get("network") or {}
        new = [layer for layer in layers if layer is not None]
        return ImportPlan(
            id=pack.id,
            version=pack.version,
            title=str(pack.manifest.get("title", pack.id)),
            kind=pack.manifest["kind"],
            network_domains=list(network.get("domains") or []) if network.get("required") else [],
            size_bytes=pack.size + sum(layer.size for layer in new),
            installed=self.installed().get(pack.id, []),
            new_layers=[layer.name for layer in new],
        )

    def _install_layer(self, bundle: Bundle, layer: BundleLayer) -> None:
        tmp = self._tmp_dir(self.libs_dir)
        try:
            for rel in layer.record:
                target = tmp.joinpath(*PurePosixPath(rel).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as fh:  # hashed again while writing
                    for chunk in bundle.read_layer_file(layer, rel):
                        fh.write(chunk)
            (tmp / "RECORD.json").write_bytes(layer.record_bytes)
            self._swap_into_place(tmp, self.libs_dir / layer.name)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise

    def _install_pack(self, pack: BundlePack) -> None:
        parent = self.automations_dir / pack.id
        tmp = self._tmp_dir(parent)
        try:
            for name, data in [
                ("manifest.json", pack.manifest_bytes),
                ("manifest.sig", pack.signature),
                *pack.files.items(),
            ]:
                target = tmp.joinpath(*PurePosixPath(name).parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as fh:
                    fh.write(data)
            verify_pack_dir(tmp, self.trusted_keys)  # what's on disk is what was verified
            self._swap_into_place(tmp, parent / pack.version)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        automations = self.index()
        entry = automations.setdefault(pack.id, {"selected": None, "versions": {}})
        entry["versions"][pack.version] = _version_info(pack.manifest)
        newest = max(entry["versions"], key=_key)
        entry["selected"] = (
            None if pack.version == newest else pack.version
        )  # an accepted downgrade
        removed = self._prune(entry, keep=pack.version)
        self._save_index(automations)  # the index first, then the folders it no longer lists
        for version in removed:
            shutil.rmtree(parent / version, ignore_errors=True)

    def _prune(self, entry: dict[str, Any], keep: str) -> list[str]:
        """Keep the version just imported plus the newest others, `keep_versions` in all."""
        others = sorted((v for v in entry["versions"] if v != keep), key=_key, reverse=True)
        removed = others[max(self.settings.keep_versions - 1, 0) :]
        for version in removed:
            del entry["versions"][version]
        return removed

    @staticmethod
    def _tmp_dir(parent: Path) -> Path:
        parent.mkdir(parents=True, exist_ok=True)
        tmp = parent / f"{TMP_PREFIX}{secrets.token_hex(8)}"
        tmp.mkdir()
        return tmp

    @staticmethod
    def _swap_into_place(tmp: Path, target: Path) -> None:
        """Rename `tmp` to `target` in one step; a damaged copy already there goes aside first."""
        old = None
        if target.exists():
            old = target.with_name(f"{OLD_PREFIX}{secrets.token_hex(8)}")
            os.rename(target, old)
        try:
            os.rename(tmp, target)
        except BaseException:
            if old is not None:
                os.rename(old, target)
            raise
        if old is not None:
            shutil.rmtree(old, ignore_errors=True)

    # --- clean-up ---------------------------------------------------------------------------

    def collect_garbage(self) -> list[str]:
        """On start (§5): drop layers no installed version uses, versions the index doesn't
        list, and leftovers of an interrupted import. Returns what it removed (store paths)."""
        automations = self.index()
        used = {
            name
            for entry in automations.values()
            for info in entry["versions"].values()
            for name in info.get("layers", [])
        }
        removed = []
        for folder in _subdirs(self.libs_dir):
            if folder.name not in used:
                removed.append(folder)
        for app in _subdirs(self.automations_dir):
            if app.name not in automations:
                removed.append(app)
                continue
            listed = automations[app.name].get("versions", {})
            removed.extend(folder for folder in _subdirs(app) if folder.name not in listed)
        for folder in removed:
            shutil.rmtree(folder, ignore_errors=True)
        for leftover in self.index_path.parent.glob(f"index.json{TMP_PREFIX}*"):
            leftover.unlink(missing_ok=True)
        return [folder.relative_to(self.root).as_posix() for folder in removed]

    # --- run (§6) ---------------------------------------------------------------------------

    def open_installed(self, automation_id: str, version: str | None = None) -> VerifiedPack:
        """Verify an installed version again, all of it, before anything from it runs."""
        version = self.resolve(automation_id, version)
        folder = self.automations_dir / automation_id / version
        if not folder.is_dir():
            raise PackError(NOT_INSTALLED)
        manifest, files = verify_pack_dir(folder, self.trusted_keys)
        if (manifest["id"], manifest["version"]) != (automation_id, version):
            raise PackError(TAMPERED)  # a signed pack, but moved into another one's place
        check_app_version(manifest, self.app_version)
        layer_dirs = verify_layers(manifest, self.libs_dir)
        self._check_license(manifest, [])
        return VerifiedPack(manifest, files, layer_dirs)

    def load(self, automation_id: str, version: str | None = None) -> LoadedSpec:
        return load_verified(self.open_installed(automation_id, version))


def _version_info(manifest: dict[str, Any]) -> dict[str, Any]:
    network = manifest.get("network") or {}
    return {
        "title": str(manifest.get("title", manifest["id"])),
        "kind": manifest["kind"],
        "layers": [name for name, _ in layer_pins(manifest)],
        "network_domains": list(network.get("domains") or []) if network.get("required") else [],
        "imported_at": _now(),
    }


def _subdirs(folder: Path) -> list[Path]:
    try:
        return [p for p in folder.iterdir() if p.is_dir() and not p.is_symlink()]
    except FileNotFoundError:
        return []
