"""Build the Runner: the engine frozen once, shared by every app (docs/ARCHITECTURE.md §8).

    python -m build.runner --out dist/runner [--extra-keys keys.json]
        [--check-pack app.mmx ...] [--launch-check]

Stages: package (PyInstaller --onedir of build/entry.py with every block module and every
module custom code may import, then trim Qt), refuse_spec (the Runner must refuse a plain
spec.json), packs (each --check-pack placed next to a copy of the Runner: smoke test on its
sample_data, plus a tampered copy that must be refused), launch_check (opens the real window
from the first pack; needs a desktop). Writes <out>/report.json with the sizes; exit 0 when
every stage passed.

The Runner trusts the public keys in build/trusted_keys.json. --extra-keys adds keys for one
build (CI signs its test packs with a throwaway key); a release never passes it.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from build.package import (
    EXCLUDES,
    LOG_TAIL_BYTES,
    StageFailed,
    engine_version,
    folder_mb,
    run,
    trim,
)
from engine.blocks import IMPLEMENTATIONS
from engine.keys import parse_keys
from tools.check_job import CODE_MODULES, NETWORK_MODULES

REPO_ROOT = Path(__file__).resolve().parent.parent
NAME = "MakeMyEXE"
# Budget from docs/ARCHITECTURE.md §8.8, reported on every build; a release enforces it.
BUDGET_MB = {"folder": 80.0, "zip": 35.0}
# Everything custom code may import must be in the Runner: the allowlist is the Runner lock.
RUNNER_MODULES = sorted(
    {m.split(":")[0] for m in IMPLEMENTATIONS.values()}
    | (CODE_MODULES - {"__future__"})
    | NETWORK_MODULES
    | {"engine.custom_api", "engine.testing"}
)
THIRD_PARTY = ("PIL", "pypdf", "fpdf", "pillow_heif")
TAMPERED_MESSAGE = "was changed after MakeMyEXE made it"


@dataclass
class RunnerReport:
    version: str = ""
    status: str = "failed"
    stage: str | None = None
    command: str | None = None
    log_tail: str | None = None
    stages: list[dict[str, Any]] = field(default_factory=list)
    packs: list[dict[str, Any]] = field(default_factory=list)
    sizes_mb: dict[str, float] = field(default_factory=dict)
    over_budget: list[str] = field(default_factory=list)
    # The biggest parts of the folder, so trimming starts where the megabytes are.
    largest_mb: dict[str, float] = field(default_factory=dict)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, indent=2), encoding="utf-8")


def merged_keys(extra: Path | None) -> dict[str, str]:
    keys = parse_keys((REPO_ROOT / "build" / "trusted_keys.json").read_text(encoding="utf-8"))
    if extra is not None:
        keys.update(parse_keys(extra.read_text(encoding="utf-8")))
    return {key_id: key.hex() for key_id, key in sorted(keys.items())}


def exe_path(folder: Path) -> Path:
    return folder / (f"{NAME}.exe" if sys.platform == "win32" else NAME)


class RunnerBuild:
    def __init__(
        self, out: Path, extra_keys: Path | None, packs: list[Path], launch_check: bool
    ) -> None:
        self.out = out.resolve()
        self.work = self.out / "work"
        self.log = self.work / "build.log"
        self.extra_keys = extra_keys
        self.packs = [p.resolve() for p in packs]
        self.launch_check = launch_check
        self.report = RunnerReport(version=engine_version())

    def run(self) -> RunnerReport:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.work.mkdir(parents=True)
        try:
            folder = self._stage("package", self._package)
            self._stage("refuse_spec", lambda: self._refuse_spec(folder))
            self._stage("packs", lambda: self._check_packs(folder))
            if self.launch_check and self.packs:
                self._stage("launch_check", lambda: self._launch_check(folder))
            self._stage("zip", lambda: self._zip(folder))
            self.report.status = "passed"
        except StageFailed as err:
            self.report.stage, self.report.command = err.stage, err.command
            self.report.log_tail = err.log_tail
        finally:
            self.report.write(self.out / "report.json")
        return self.report

    def _stage(self, name: str, action):
        started = time.monotonic()
        try:
            return action()
        except StageFailed:
            raise
        except Exception as err:  # a bug in a stage itself: still report it
            detail = f"{type(err).__name__}: {err}"
            raise StageFailed(name, f"build.runner ({name})", detail) from err
        finally:
            seconds = round(time.monotonic() - started, 1)
            self.report.stages.append({"name": name, "seconds": seconds})

    def _package(self) -> Path:
        data = self.work / "data"
        data.mkdir()
        (data / "trusted_keys.json").write_text(json.dumps(merged_keys(self.extra_keys), indent=2))
        marker = {"name": NAME, "version": self.report.version}
        (data / "runner.json").write_text(json.dumps(marker))
        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--onedir",
            "--windowed",
            "--name",
            NAME,
            "--distpath",
            str(self.work / "dist"),
            "--workpath",
            str(self.work / "pyinstaller"),
            "--specpath",
            str(self.work),
            "--add-data",
            f"{data / 'trusted_keys.json'}{_sep()}.",
            "--add-data",
            f"{data / 'runner.json'}{_sep()}.",
            "--collect-data",
            "engine",
        ]
        for module in RUNNER_MODULES:
            cmd += ["--hidden-import", module]
        for package in THIRD_PARTY:
            cmd += ["--collect-submodules", package]
        for module in EXCLUDES:
            cmd += ["--exclude-module", module]
        cmd.append(str(Path(__file__).with_name("entry.py")))
        run("package", cmd, self.log)
        folder = self.work / "dist" / NAME
        self.report.sizes_mb["before_trim"] = folder_mb(folder)
        trim(folder / "_internal")
        self.report.sizes_mb["folder"] = folder_mb(folder)
        self.report.largest_mb = largest_parts(folder)
        return folder

    def _exe(self, stage: str, exe: Path, args: list[str], qt: str | None = "offscreen"):
        result = exe.parent / f"{stage}-result.json"
        env = {"MAKEMYEXE_DATA_DIR": str(self.work / "appdata"), "QT_QPA_PLATFORM": qt}
        failure: StageFailed | None = None
        try:
            run(stage, [str(exe), *args, "--report", str(result)], self.log, env)
        except StageFailed as err:
            failure = err
        report = json.loads(result.read_text(encoding="utf-8")) if result.is_file() else {}
        return (1 if failure else 0), report, failure

    def _refuse_spec(self, folder: Path) -> None:
        spec = REPO_ROOT / "automations" / "invoice-generator" / "spec.json"
        code, report, _ = self._exe("refuse_spec", exe_path(folder), [str(spec), "--smoke-test"])
        if code == 0 or "only signed" not in str(report.get("error", "")):
            raise StageFailed("refuse_spec", "Runner spec.json --smoke-test", json.dumps(report))

    def _app_copy(self, folder: Path, pack: Path, name: str) -> Path:
        target = self.work / "apps" / name
        shutil.copytree(folder, target, symlinks=True)
        shutil.copy2(pack, target / "app.mmx")
        return exe_path(target)

    def _check_packs(self, folder: Path) -> None:
        for i, pack in enumerate(self.packs):
            exe = self._app_copy(folder, pack, f"app-{i}")
            code, report, failure = self._exe(f"smoke-{i}", exe, ["--smoke-test"])
            entry = {"pack": pack.parent.name or pack.name, "smoke_test": report.get("status")}
            if code != 0 or report.get("status") != "passed":
                raise StageFailed(
                    "packs", f"Runner --smoke-test ({entry['pack']})", _tail(failure, report)
                )
            changed = _tamper(pack, self.work / f"tampered-{i}.mmx")
            tampered = self._app_copy(folder, changed, f"t-{i}")
            code, report, _ = self._exe(f"tampered-{i}", tampered, ["--smoke-test"])
            entry["tampered_refused"] = code != 0 and TAMPERED_MESSAGE in str(report.get("error"))
            if not entry["tampered_refused"]:
                raise StageFailed("packs", "Runner with a changed app.mmx", json.dumps(report))
            self.report.packs.append(entry)

    def _launch_check(self, folder: Path) -> None:
        exe = exe_path(self.work / "apps" / "app-0")
        code, report, failure = self._exe("launch_check", exe, ["--launch-check"], qt=None)
        if code != 0 or report.get("status") != "passed":
            raise StageFailed("launch_check", "Runner --launch-check", _tail(failure, report))

    def _zip(self, folder: Path) -> Path:
        target = self.out / f"{NAME}-runner-{self.report.version}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    archive.write(path, path.relative_to(folder))
        self.report.sizes_mb["zip"] = round(target.stat().st_size / 1_000_000, 1)
        self.report.over_budget = [
            f"{part}: {self.report.sizes_mb[part]} MB > {limit} MB"
            for part, limit in BUDGET_MB.items()
            if self.report.sizes_mb.get(part, 0) > limit
        ]
        return target


def largest_parts(folder: Path, count: int = 25) -> dict[str, float]:
    """Sizes by part: files and folders two levels below _internal/ (PySide6/Qt6Gui.dll)."""
    sizes: dict[str, int] = {}
    for path in folder.rglob("*"):
        if not path.is_file() or path.is_symlink():
            continue
        parts = path.relative_to(folder).parts
        key = "/".join(parts[:3] if parts[0] == "_internal" else parts[:1])
        sizes[key] = sizes.get(key, 0) + path.stat().st_size
    top = sorted(sizes.items(), key=lambda item: -item[1])[:count]
    return {key: round(size / 1_000_000, 1) for key, size in top}


def _sep() -> str:
    return ";" if sys.platform == "win32" else ":"


def _tail(failure: StageFailed | None, report: dict[str, Any]) -> str:
    text = json.dumps(report, indent=2) if report else ""
    if failure is not None:
        text += "\n" + failure.log_tail
    return text[-LOG_TAIL_BYTES:]


def _tamper(pack: Path, target: Path) -> Path:
    """A copy of the pack with spec.json changed by one byte (and the signature untouched)."""
    with zipfile.ZipFile(pack) as src, zipfile.ZipFile(target, "w") as dst:
        for info in src.infolist():
            data = src.read(info)
            dst.writestr(info, data + b" " if info.filename == "spec.json" else data)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m build.runner", description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("dist/runner"))
    parser.add_argument("--extra-keys", type=Path, help="trust these keys too (CI test packs)")
    parser.add_argument("--check-pack", type=Path, action="append", default=[], metavar="MMX")
    parser.add_argument("--launch-check", action="store_true", help="needs a desktop")
    args = parser.parse_args(argv)
    report = RunnerBuild(args.out, args.extra_keys, args.check_pack, args.launch_check).run()
    keys = ("status", "stage", "packs", "sizes_mb", "over_budget", "largest_mb")
    print(json.dumps({k: getattr(report, k) for k in keys}, indent=2))
    if report.status != "passed":
        print(f"\n{report.stage} failed: {report.command}\n{report.log_tail}", file=sys.stderr)
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
