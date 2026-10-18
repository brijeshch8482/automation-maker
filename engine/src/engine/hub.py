"""Hub mode without the window: what the list shows, imports, and starting automations.

    MakeMyEXE.exe                       the Hub (engine/ui/hub.py)
    MakeMyEXE.exe --import <file.mmx>   the Hub, adding that file (the .mmx file association)
    MakeMyEXE.exe --run <id>[@<ver>]    one automation, in its own process (engine/__main__.py)

The Hub has no network code at all (docs/DESKTOP_APP.md §3.3): the website opens in the browser,
and the offline guard is on in this process too. Every automation runs in a process of its own,
with only its own layers on sys.path, so a crash or a heavy import never reaches the Hub.
"""

from __future__ import annotations

import json
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from engine.bundle import parse_version
from engine.pack import PackError, verify_pack_dir
from engine.shortcuts import start_menu_dir, write_shortcut
from engine.store import AppStore, ImportPlan, ImportResult

WEBSITE = "https://makemyexe.pages.dev"
PREINSTALLED_DIR = "preinstalled"  # next to the exe: the free set the installer ships (§15)
CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def display_id(install_id: str) -> str:
    """MMX-XXXX-XXXX-XXXX: 55 bits of the install id in base32, plus a check character."""
    value = int(install_id, 16) >> (128 - 55)
    digits = [(value >> (5 * (10 - i))) & 31 for i in range(11)]
    check = sum((2 * i + 1) * d for i, d in enumerate(digits)) % 32
    text = "".join(CROCKFORD[d] for d in [*digits, check])
    return f"MMX-{text[:4]}-{text[4:8]}-{text[8:]}"


@dataclass
class HubEntry:
    """One automation in the list. `problem` is set if its installed copy fails the check."""

    id: str
    version: str
    versions: list[str]  # installed, newest first
    title: str
    description: str = ""
    network_domains: list[str] = field(default_factory=list)
    problem: str | None = None


def entries(store: AppStore) -> list[HubEntry]:
    """The list, each version checked (signature and files; layers are checked at run)."""
    result = []
    for ident, versions in sorted(store.installed().items()):
        if not versions:
            continue
        version = store.resolve(ident)
        info = store.index()[ident]["versions"][version]
        entry = HubEntry(ident, version, versions, str(info.get("title", ident)))
        try:
            manifest, files = verify_pack_dir(
                store.automations_dir / ident / version, store.trusted_keys
            )
            if (manifest["id"], manifest["version"]) != (ident, version):
                raise PackError("This automation was changed after it was added.")
            spec = json.loads(files["spec.json"])
            entry.title = str(spec.get("title", entry.title))
            entry.description = str(spec.get("description", ""))
            network = spec.get("network") or {}
            if network.get("required"):
                entry.network_domains = list(network.get("domains") or [])
        except (PackError, ValueError, KeyError, OSError):
            entry.problem = (
                "This automation was changed after it was added. Add it again from the website."
            )
        result.append(entry)
    return sorted(result, key=lambda e: e.title.lower())


def launch_command(automation_id: str, version: str | None = None) -> list[str]:
    target = f"{automation_id}@{version}" if version else automation_id
    if getattr(sys, "frozen", False):
        return [sys.executable, "--run", target]
    return [sys.executable, "-m", "engine", "--run", target]


def launch(automation_id: str, version: str | None = None) -> subprocess.Popen[bytes]:
    """Start the automation in a new process; the Hub doesn't wait for it."""
    return subprocess.Popen(launch_command(automation_id, version), close_fds=True)


def exe_path() -> Path | None:
    """The installed MakeMyEXE.exe, which shortcuts point at; None when run from source."""
    return Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None


def add_shortcuts(store: AppStore, ids: list[str] | None = None) -> list[Path]:
    """Start menu entries for these automations (all, by default), when installed on Windows."""
    folder, exe = start_menu_dir(), exe_path()
    if folder is None or exe is None:
        return []
    made = []
    for entry in entries(store):
        if ids is None or entry.id in ids:
            made.append(write_shortcut(folder, entry.title, entry.id, exe))
    return made


def only_newer(plan: ImportPlan) -> bool:
    """For the pre-installed set: add what's missing or newer, never replace or downgrade."""
    if not plan.installed:
        return True
    return (parse_version(plan.version) or (0, 0, 0)) > (
        parse_version(plan.installed[0]) or (0, 0, 0)
    )


def import_preinstalled(store: AppStore, folder: Path | None) -> list[ImportResult]:
    """The free set shipped next to the exe. A file that fails its check is skipped."""
    results: list[ImportResult] = []
    if folder is None or not folder.is_dir():
        return results
    for path in sorted(folder.glob("*.mmx")):
        try:
            results.extend(store.import_bundle(path, confirm=only_newer))
        except PackError:
            continue
    return results


def preinstalled_dir() -> Path | None:
    exe = exe_path()
    return exe.parent / PREINSTALLED_DIR if exe else None


def start_hub(store: AppStore, preinstalled: Path | None = None) -> list[ImportResult]:
    """What the Hub does on every start: tidy the store, add the free set, make shortcuts."""
    store.collect_garbage()
    results = import_preinstalled(store, preinstalled)
    add_shortcuts(store)
    return results


def import_file(
    store: AppStore, path: Path, confirm: Callable[[ImportPlan], bool]
) -> list[ImportResult]:
    results = store.import_bundle(path, confirm=confirm)
    add_shortcuts(store, [r.plan.id for r in results if r.imported])
    return results
