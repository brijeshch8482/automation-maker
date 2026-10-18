"""The MakeMyEXE installer (docs/DESKTOP_APP.md §9): sign the free set, build, check, publish.

    python -m build.installer packs --out <dir> [--key-id catalog-1]    PEM in PACK_SIGNING_KEY
    python -m build.installer make --runner <folder> --preinstalled <dir> --out <dir>
    python -m build.installer check <setup.exe> --expect <id> ... --out <dir> [--this-pc]
    python -m build.installer publish <MakeMyEXE-Setup-x.y.z.exe>        R2_* settings in the env

`packs` signs every catalog automation as `<id>.mmx`, the pre-installed set (§15: all four), and
refuses a key the Runner wouldn't trust. `make` runs Inno Setup (installer/MakeMyEXE.iss) on
Windows. `check` installs for real into this user's profile, so it runs only on a CI machine (or
with --this-pc): silent install, HKCU registrations only, Start menu, the Hub's launch check
with the free set, every automation's smoke test from the store, a .mmx opened the way the file
association does, then uninstall twice (keeping the store, then removing it with /REMOVESTORE),
and a file in Documents must survive both. Writes report.json. `publish` uploads the installer
to R2 as app/<version>/ and the pointer app/latest.json (release workflow, environment catalog).
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from build import pack as build_pack
from build.publish import PublishError, upload
from build.publish_packs import KeyNotTrusted, public_key_hex, trusted_keys

REPO_ROOT = Path(__file__).resolve().parent.parent
ISS = REPO_ROOT / "installer" / "MakeMyEXE.iss"
APP_ID = "{6F1E3B52-8A0D-4E7C-9B1A-4D2C5E7F8A90}"
NAME = "MakeMyEXE"
R2_SETTINGS = ("R2_ACCOUNT_ID", "R2_ACCESS_KEY_ID", "R2_SECRET_ACCESS_KEY", "R2_BUCKET")
SETUP_NAME = re.compile(r"^MakeMyEXE-Setup-(\d+\.\d+\.\d+)\.exe$")
UNINSTALL_WAIT_S = 180
TIMEOUT_S = {"make": 900}
LOG_TAIL = 4000


class StageFailed(Exception):
    """Standard library only, like the rest of this module (the signing job has no venv)."""

    def __init__(self, stage: str, command: str, log_tail: str) -> None:
        super().__init__(f"{stage} failed")
        self.stage, self.command, self.log_tail = stage, command, log_tail


def run(stage: str, cmd: list[str], log: Path, env: dict[str, str | None] | None = None) -> None:
    """Run a command, appending its output to the log; StageFailed with the log tail if it fails."""
    full = dict(os.environ)
    for key, value in (env or {}).items():
        if value is None:
            full.pop(key, None)
        else:
            full[key] = value
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as out:
        out.write(f"\n$ {' '.join(cmd)}\n".encode())
        out.flush()
        try:
            code = subprocess.run(
                cmd,
                stdout=out,
                stderr=subprocess.STDOUT,
                env=full,
                timeout=TIMEOUT_S.get(stage, 300),
                check=False,
            ).returncode
        except subprocess.TimeoutExpired:
            code = -1
    if code != 0:
        tail = log.read_bytes()[-LOG_TAIL:].decode("utf-8", "replace")
        raise StageFailed(stage, " ".join(cmd[:2]), tail)


# --- packs -------------------------------------------------------------------------------------


def sign_packs(
    automations: Path, out: Path, pem: str, key_id: str, trusted_file: Path | None, version: str
) -> list[Path]:
    """Every catalog automation as <id>.mmx. With `trusted_file`, the key must be in it."""
    if trusted_file is not None:
        public = public_key_hex(pem)
        if trusted_keys(trusted_file).get(key_id) != public:
            raise KeyNotTrusted(
                f"the signing key {key_id!r} is not in build/trusted_keys.json, so the app "
                f'would refuse its own free set. Add "{key_id}": "{public}" (a public key) in a PR.'
            )
    out.mkdir(parents=True, exist_ok=True)
    made = []
    with tempfile.TemporaryDirectory(prefix="makemyexe-free-") as tmp:
        for app in sorted(p for p in automations.iterdir() if (p / "spec.json").is_file()):
            pack = build_pack.make_pack(app, Path(tmp) / app.name, "catalog", key_id, pem, version)
            target = out / f"{app.name}.mmx"
            shutil.copy2(pack, target)
            made.append(target)
    return made


# --- make --------------------------------------------------------------------------------------


def iscc() -> Path:
    candidates = [
        os.environ.get("ISCC"),
        shutil.which("iscc"),
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return Path(candidate)
    raise StageFailed("make", "ISCC.exe", "Inno Setup 6 is not installed (choco install innosetup)")


def make_installer(runner: Path, preinstalled: Path, out: Path, version: str, log: Path) -> Path:
    if not (runner / f"{NAME}.exe").is_file():
        raise StageFailed("make", "build.installer make", f"{NAME}.exe is not in the Runner folder")
    if not list(preinstalled.glob("*.mmx")):
        raise StageFailed("make", "build.installer make", "no pre-installed .mmx files")
    out.mkdir(parents=True, exist_ok=True)
    cmd = [
        str(iscc()),
        f"/DAppVersion={version}",
        f"/DRunnerDir={runner.resolve()}",
        f"/DPreinstalledDir={preinstalled.resolve()}",
        f"/DOutputDir={out.resolve()}",
        str(ISS),
    ]
    run("make", cmd, log)
    setup = out / f"MakeMyEXE-Setup-{version}.exe"
    if not setup.is_file():
        raise StageFailed("make", "ISCC.exe", f"{setup.name} was not made")
    return setup


# --- check (Windows, installs for real) -----------------------------------------------------------


@dataclass
class CheckReport:
    status: str = "failed"
    stage: str | None = None
    detail: str | None = None
    version: str = ""
    size_mb: float = 0.0
    installed_mb: float = 0.0
    stages: list[str] = field(default_factory=list)
    automations: list[str] = field(default_factory=list)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, indent=2), encoding="utf-8")


class InstallerCheck:
    def __init__(self, setup: Path, expect: list[str], out: Path) -> None:
        self.setup = setup.resolve()
        self.expect = sorted(expect)
        self.out = out.resolve()
        self.log = self.out / "check.log"
        local = Path(os.environ["LOCALAPPDATA"])
        roaming = Path(os.environ["APPDATA"])
        self.app_dir = local / "Programs" / NAME
        self.exe = self.app_dir / f"{NAME}.exe"
        self.store = local / NAME
        self.settings = roaming / NAME
        self.start_menu = roaming / "Microsoft" / "Windows" / "Start Menu" / "Programs" / NAME
        self.marker = Path.home() / "Documents" / NAME / f"installer-check-{os.getpid()}.txt"
        self.report = CheckReport()

    def run(self) -> CheckReport:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.out.mkdir(parents=True)
        match = SETUP_NAME.match(self.setup.name)
        self.report.version = match.group(1) if match else ""
        self.report.size_mb = round(self.setup.stat().st_size / 1_000_000, 1)
        self.marker.parent.mkdir(parents=True, exist_ok=True)
        self.marker.write_text("A file the user made. Uninstall must leave it.", encoding="utf-8")
        try:
            self._stage("install", self._install)
            self._stage("registry", self._registry)
            self._stage("hub", self._hub)
            self._stage("run", self._run_each)
            self._stage("open_file", self._open_file)
            self._stage("uninstall_keep", lambda: self._uninstall(remove_store=False))
            self._stage("reinstall", self._install)
            self._stage("uninstall_remove", lambda: self._uninstall(remove_store=True))
            self.report.status = "passed"
        except StageFailed as err:
            self.report.stage, self.report.detail = err.stage, err.log_tail
        finally:
            self.marker.unlink(missing_ok=True)  # our own test file, made above
            self.report.write(self.out / "report.json")
        return self.report

    def _stage(self, name: str, action) -> None:
        try:
            action()
        except StageFailed:
            raise
        except Exception as err:
            raise StageFailed(
                name, f"build.installer ({name})", f"{type(err).__name__}: {err}"
            ) from err
        self.report.stages.append(name)

    def _fail(self, stage: str, detail: str) -> None:
        raise StageFailed(stage, f"build.installer ({stage})", detail)

    def _exe(self, stage: str, args: list[str], qt: str | None = None) -> dict[str, Any]:
        result = self.out / f"{stage}-{len(self.report.stages)}.json"
        env = {"QT_QPA_PLATFORM": qt}
        with contextlib.suppress(StageFailed):  # the report says what went wrong
            run(stage, [str(self.exe), *args, "--report", str(result)], self.log, env)
        return json.loads(result.read_text(encoding="utf-8")) if result.is_file() else {}

    def _install(self) -> None:
        log = self.out / "setup.log"
        run(
            "install",
            [str(self.setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", f"/LOG={log}"],
            self.log,
        )
        if not self.exe.is_file():
            self._fail("install", f"{self.exe.name} is not in %LOCALAPPDATA%\\Programs\\{NAME}")
        if not (self.app_dir / "preinstalled").is_dir():
            self._fail("install", "the pre-installed set is missing")
        if not (self.start_menu / f"{NAME}.lnk").is_file():
            self._fail("install", "the Start menu entry is missing")
        size = sum(p.stat().st_size for p in self.app_dir.rglob("*") if p.is_file())
        self.report.installed_mb = round(size / 1_000_000, 1)

    def _registry(self) -> None:
        import winreg

        def value(root: int, key: str) -> str | None:
            try:
                with winreg.OpenKey(root, key) as handle:
                    return str(winreg.QueryValueEx(handle, "")[0])
            except OSError:
                return None

        cu, lm = winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE
        if value(cu, r"Software\Classes\.mmx") != "MakeMyEXE.Bundle":
            self._fail("registry", ".mmx is not registered for this user")
        command = value(cu, r"Software\Classes\MakeMyEXE.Bundle\shell\open\command") or ""
        if command != f'"{self.exe}" --import "%1"':
            self._fail("registry", f"unexpected open command: {command}")
        for key in (r"Software\Classes\.mmx", r"Software\Classes\MakeMyEXE.Bundle"):
            if value(lm, key) is not None:
                self._fail("registry", f"HKLM\\{key} was written (HKCU only)")
        uninstall = rf"Software\Microsoft\Windows\CurrentVersion\Uninstall\{APP_ID}_is1"
        try:
            with winreg.OpenKey(cu, uninstall) as handle:
                winreg.QueryValueEx(handle, "UninstallString")
        except OSError:
            self._fail("registry", "no per-user uninstall entry")

    def _hub(self) -> None:
        report = self._exe("hub", ["--hub", "--launch-check"])
        self.report.automations = sorted(report.get("automations", []))
        if report.get("status") != "passed" or self.report.automations != self.expect:
            self._fail("hub", json.dumps(report))
        shortcuts = sorted(p.stem for p in self.start_menu.glob("*.lnk"))
        if len(shortcuts) != len(self.expect) + 1:
            self._fail("hub", f"Start menu entries: {shortcuts}")

    def _run_each(self) -> None:
        for automation in self.expect:
            report = self._exe("run", ["--run", automation, "--smoke-test"], qt="offscreen")
            if report.get("status") != "passed":
                self._fail("run", f"{automation}: {json.dumps(report)[-2000:]}")

    def _open_file(self) -> None:
        """What a double-click on a .mmx runs, with the defaults answered (it reinstalls)."""
        bundle = sorted((self.app_dir / "preinstalled").glob("*.mmx"))[0]
        copy = self.out / bundle.name
        shutil.copy2(bundle, copy)
        report = self._exe("open", ["--import", str(copy), "--launch-check"])
        if report.get("status") != "passed" or len(report.get("imported", [])) != 1:
            self._fail("open_file", json.dumps(report))

    def _uninstall(self, remove_store: bool) -> None:
        uninstaller = self.app_dir / "unins000.exe"
        args = [str(uninstaller), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"]
        run("uninstall", [*args, "/REMOVESTORE"] if remove_store else args, self.log)
        deadline = time.monotonic() + UNINSTALL_WAIT_S  # the uninstaller re-runs from %TEMP%
        while self.exe.exists() and time.monotonic() < deadline:
            time.sleep(1)
        stage = "uninstall_remove" if remove_store else "uninstall_keep"
        if self.exe.exists():
            self._fail(stage, "the app is still there")
        time.sleep(3)  # usPostUninstall runs after the files are gone
        if self.start_menu.exists():
            self._fail(stage, "the Start menu folder is still there")
        if not self.marker.is_file():
            self._fail(stage, "a file in Documents was removed")
        has_store = (self.store / "store" / "index.json").is_file()
        if remove_store and (has_store or self.settings.exists()):
            self._fail(stage, "the store or settings are still there after /REMOVESTORE")
        if not remove_store and not has_store:
            self._fail(stage, "the store was removed although the answer was Keep")


# --- publish -----------------------------------------------------------------------------------


def publish_installer(setup: Path, env: dict[str, str]) -> dict[str, Any]:
    match = SETUP_NAME.match(setup.name)
    if not match:
        raise PublishError(f"unexpected installer name {setup.name}")
    missing = [name for name in R2_SETTINGS if not env.get(name)]
    if missing:
        raise PublishError(f"R2 is not configured; missing: {', '.join(missing)}")
    version = match.group(1)
    key = f"app/{version}/{setup.name}"
    data = setup.read_bytes()
    latest = {
        "version": version,
        "key": key,
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }
    upload(setup, key, env, "application/vnd.microsoft.portable-executable")
    with tempfile.TemporaryDirectory() as tmp:
        pointer = Path(tmp) / "latest.json"
        pointer.write_text(json.dumps(latest, indent=2), encoding="utf-8")
        upload(pointer, "app/latest.json", env, "application/json")
    return latest


# --- CLI ---------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m build.installer", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    packs = sub.add_parser("packs", help="sign the pre-installed set")
    packs.add_argument("--out", type=Path, required=True)
    packs.add_argument("--automations", type=Path, default=REPO_ROOT / "automations")
    packs.add_argument("--key-id", default=os.environ.get("PACK_KEY_ID") or "catalog-1")
    packs.add_argument("--version", default=None, help="Runner version it was tested with")
    packs.add_argument(
        "--untrusted-ok", action="store_true", help="a throwaway test key (pull requests)"
    )
    make = sub.add_parser("make", help="build the installer with Inno Setup")
    make.add_argument("--runner", type=Path, required=True)
    make.add_argument("--preinstalled", type=Path, required=True)
    make.add_argument("--out", type=Path, required=True)
    make.add_argument("--version", default=None)
    check = sub.add_parser("check", help="install, run, uninstall (changes this user profile)")
    check.add_argument("setup", type=Path)
    check.add_argument("--expect", nargs="+", required=True, metavar="ID")
    check.add_argument("--out", type=Path, required=True)
    check.add_argument("--this-pc", action="store_true", help="really install on this PC")
    publish = sub.add_parser("publish", help="upload to R2 as app/<version>/")
    publish.add_argument("setup", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "packs":
            pem = os.environ.get("PACK_SIGNING_KEY", "")
            if not pem.strip():
                raise PublishError("PACK_SIGNING_KEY is not set (docs/DEPLOY.md §9)")
            trusted = None if args.untrusted_ok else REPO_ROOT / "build" / "trusted_keys.json"
            made = sign_packs(
                args.automations,
                args.out,
                pem,
                args.key_id,
                trusted,
                args.version or build_pack.engine_version(),
            )
            print("\n".join(str(p) for p in made))
        elif args.command == "make":
            from build.runner import runner_version  # the engine's version (needs the venv)

            setup = make_installer(
                args.runner,
                args.preinstalled,
                args.out,
                args.version or runner_version(),
                args.out / "make.log",
            )
            print(f"{setup} ({setup.stat().st_size / 1_000_000:.1f} MB)")
        elif args.command == "check":
            if sys.platform != "win32" or not (args.this_pc or os.environ.get("CI") == "true"):
                parser.error("check installs for real: Windows CI only, or pass --this-pc")
            report = InstallerCheck(args.setup, args.expect, args.out).run()
            print(json.dumps(report.__dict__, indent=2))
            return 0 if report.status == "passed" else 1
        else:
            env = {name: os.environ.get(name, "") for name in R2_SETTINGS}
            print(json.dumps(publish_installer(args.setup, env), indent=2))
    except (PublishError, StageFailed) as err:
        detail = err.log_tail if isinstance(err, StageFailed) else str(err)
        print(f"error: {detail}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
