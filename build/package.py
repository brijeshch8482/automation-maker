"""Package one automation as a Windows app: folder + Guide.pdf + zip (docs/ROUTINES.md §5).

    python -m build.package automations/make-pdf --out dist/ [--launch-check]
        [--expect-spec-sha256 HEX]

Stages: validate, package (PyInstaller --onedir, then trim Qt), smoke_test (the packaged app on
its sample_data), launch_check (opens the real window; needs a desktop), guide (screenshots from
the packaged app), guide_pdf, zip. The result is always written to <out>/report.json; on a
failure it names the stage, the command and the end of the log, which is what the repair
routine reads. Exit code 0 when every stage passed, else 1.

With --expect-spec-sha256 (custom jobs: the fingerprint of the spec the user confirmed, from
spec.fingerprint), validate fails unless spec.json is exactly that spec.

The automation folder holds spec.json, optional samples/ and optional custom_step.py. Nothing
else from it is bundled (tests and caches stay out).
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from build.guide_pdf import make_guide
from engine.blocks import block_module
from spec.fingerprint import spec_sha256
from spec.models import AutomationSpec
from spec.validate import validate_spec

REPO_ROOT = Path(__file__).resolve().parent.parent
LOG_TAIL_BYTES = 8_000
STAGE_TIMEOUT = {"package": 1200, "smoke_test": 300, "launch_check": 120, "guide": 300}

# Bundled from the automation folder; everything else there is left out.
APP_FILES = ("spec.json", "custom_step.py")
APP_DIRS = ("samples",)

# Never needed by an EXE. cryptography arrives through pypdf's optional AES support (the engine
# refuses encrypted PDFs), the rest through optional imports of other libraries.
EXCLUDES = (
    "cryptography",
    "tkinter",
    "pydoc",
    "PySide6.QtNetwork",
    "PySide6.QtDBus",
    "PySide6.QtOpenGL",
    "PySide6.QtQml",
    "PySide6.QtQuick",
    "PySide6.QtPdf",
    "api",
    "fastapi",
    "sqlalchemy",
    "pytest",
)

# Only bundled when a block needs it: pypdf imports fontTools optionally (text extraction),
# but only fpdf2 (making PDFs) needs it. custom.step may use anything, so it keeps everything.
NEEDED_BY = {
    "fontTools": {"pdf.render_template", "pdf.from_files", "custom.step"},
    "uharfbuzz": {"pdf.render_template", "pdf.from_files", "custom.step"},
}


def excludes(spec: AutomationSpec) -> list[str]:
    blocks = {step.block for step in spec.steps}
    return [*EXCLUDES, *(m for m, users in NEEDED_BY.items() if not blocks & users)]


# Removed from the packaged folder after PyInstaller (globs under _internal/). The app shows only
# widgets, in English: no translations, no software OpenGL, no network or TLS plugins.
TRIM = (
    "PySide6/translations",
    "PySide6/Qt/translations",
    "PySide6/opengl32sw.dll",
    "PySide6/d3dcompiler_47.dll",
    "PySide6/Qt6Network.dll",
    "PySide6/Qt6Pdf.dll",
    "PySide6/Qt6Quick.dll",
    "PySide6/Qt6Qml*.dll",
    "PySide6/plugins/networkinformation",
    "PySide6/plugins/tls",
    "PySide6/plugins/generic",
    "PySide6/plugins/platforminputcontexts",
    "PySide6/Qt/plugins/networkinformation",
    "PySide6/Qt/plugins/tls",
    "PySide6/Qt/plugins/generic",
    "PySide6/Qt/plugins/platforminputcontexts",
    "PySide6/Qt/plugins/egldeviceintegrations",
    "PySide6/Qt/plugins/wayland-*",
    "PySide6/Qt/lib/libQt6Network.so*",
    "PySide6/Qt/lib/libQt6WaylandClient.so*",
    "PySide6/Qt/lib/libQt6EglFS*",
    "PySide6/Qt/lib/libQt6WlShellIntegration.so*",
)


class StageFailed(Exception):
    def __init__(self, stage: str, command: str, log_tail: str, test: str | None = None) -> None:
        super().__init__(f"{stage} failed")
        self.stage, self.command, self.log_tail, self.test = stage, command, log_tail, test


@dataclass
class Report:
    automation: str = ""
    version: str = ""
    exe: str = ""
    engine_version: str = ""
    status: str = "failed"
    stage: str | None = None
    command: str | None = None
    test: str | None = None
    log_tail: str | None = None
    stages: list[dict[str, Any]] = field(default_factory=list)
    sizes_mb: dict[str, float] = field(default_factory=dict)

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.__dict__, indent=2), encoding="utf-8")


def exe_name(title: str) -> str:
    """ "Make PDF" -> "MakePDF", "invoice generator" -> "InvoiceGenerator"."""
    words = re.findall(r"[A-Za-z0-9]+", title)
    name = "".join(w if w.isupper() else w[:1].upper() + w[1:] for w in words)
    return name[:40] or "Automation"


def engine_version() -> str:
    marker = REPO_ROOT / "ENGINE_VERSION"
    return marker.read_text(encoding="utf-8").strip() if marker.is_file() else "dev"


def hidden_imports(spec: AutomationSpec, app_dir: Path) -> list[str]:
    """Modules PyInstaller can't see: the spec's block modules and custom_step.py's imports."""
    modules = {m for step in spec.steps if (m := block_module(step.block))}
    custom = app_dir / "custom_step.py"
    if custom.is_file():
        for node in ast.walk(ast.parse(custom.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                modules.add(node.module)
    return sorted(modules)


def stage_app(src: Path, dest: Path) -> Path:
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for name in APP_FILES:
        if (src / name).is_file():
            shutil.copy2(src / name, dest / name)
    for name in APP_DIRS:
        if (src / name).is_dir():
            shutil.copytree(src / name, dest / name, ignore=shutil.ignore_patterns("__pycache__"))
    return dest


def trim(internal: Path) -> list[str]:
    removed = []
    for pattern in TRIM:
        for path in sorted(internal.glob(pattern)):
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(path.relative_to(internal).as_posix())
    return removed


def folder_mb(path: Path) -> float:
    # Linux builds link shared libraries with symlinks; count each file once.
    total = sum(p.stat().st_size for p in path.rglob("*") if p.is_file() and not p.is_symlink())
    return round(total / 1_000_000, 1)


def run(stage: str, cmd: list[str], log: Path, env: dict[str, str | None] | None = None) -> None:
    """Run one command, appending its output to the build log. env: None removes a variable."""
    full = dict(os.environ)
    for key, value in (env or {}).items():
        if value is None:
            full.pop(key, None)
        else:
            full[key] = value
    command = " ".join(_display(c) for c in cmd)
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("ab") as out:
        out.write(f"\n$ {command}\n".encode())
        out.flush()
        try:
            code = subprocess.run(
                cmd,
                stdout=out,
                stderr=subprocess.STDOUT,
                env=full,
                timeout=STAGE_TIMEOUT.get(stage, 300),
                check=False,
            ).returncode
        except subprocess.TimeoutExpired:
            out.write(f"\ntimed out after {STAGE_TIMEOUT.get(stage, 300)} s\n".encode())
            code = -1
    if code != 0:
        raise StageFailed(stage, command, tail(log))


def tail(path: Path, limit: int = LOG_TAIL_BYTES) -> str:
    if not path.is_file():
        return ""
    data = path.read_bytes()[-limit:]
    return data.decode("utf-8", "replace")


def _display(part: str) -> str:
    """Commands in the report use paths relative to the repo where possible."""
    try:
        return Path(part).resolve().relative_to(REPO_ROOT).as_posix()
    except (ValueError, OSError):
        return part


def _read_json(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


class Packager:
    def __init__(
        self, app_dir: Path, out: Path, launch_check: bool, expect_spec_sha256: str | None = None
    ) -> None:
        self.app_dir = app_dir.resolve()
        self.expect_spec_sha256 = expect_spec_sha256
        self.out = out.resolve()
        self.work = self.out / "work"
        self.launch_check = launch_check
        self.report = Report(engine_version=engine_version())
        self.log = self.work / "build.log"

    def run(self) -> Report:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.work.mkdir(parents=True)
        try:
            spec = self._stage("validate", self._validate)
            exe = self._stage("package", lambda: self._package(spec))
            self._stage("smoke_test", lambda: self._smoke_test(exe))
            if self.launch_check:
                self._stage("launch_check", lambda: self._launch_check(exe))
            screens = self.out / "screenshots"
            self._stage("guide", lambda: self._guide(exe, screens))
            guide = self._stage("guide_pdf", lambda: self._guide_pdf(spec, screens))
            self._stage("zip", lambda: self._zip(exe.parent, guide))
            self.report.status = "passed"
        except StageFailed as err:
            self.report.stage, self.report.command = err.stage, err.command
            self.report.test, self.report.log_tail = err.test, err.log_tail
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
            raise StageFailed(name, f"build.package ({name})", detail) from err
        finally:
            seconds = round(time.monotonic() - started, 1)
            self.report.stages.append({"name": name, "seconds": seconds})

    def _validate(self) -> AutomationSpec:
        spec_path = self.app_dir / "spec.json"
        command = f"python -m tools.validate_spec {_display(str(spec_path))}"
        try:
            data = json.loads(spec_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise StageFailed("validate", command, f"spec.json could not be read: {err}") from err
        if self.expect_spec_sha256 and spec_sha256(data) != self.expect_spec_sha256.lower():
            raise StageFailed(
                "validate",
                "spec fingerprint check",
                "spec.json is not the spec the user confirmed; write it exactly as given",
            )
        spec, issues = validate_spec(data)
        if issues or spec is None:
            raise StageFailed("validate", command, "\n".join(str(i) for i in issues))
        self.report.automation, self.report.version = spec.id, spec.version
        self.report.exe = exe_name(spec.title)
        return spec

    def _package(self, spec: AutomationSpec) -> Path:
        name = self.report.exe
        app = stage_app(self.app_dir, self.work / "app")
        cmd = [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--onedir",
            "--windowed",
            "--name",
            name,
            "--distpath",
            str(self.work / "dist"),
            "--workpath",
            str(self.work / "pyinstaller"),
            "--specpath",
            str(self.work),
            "--add-data",
            f"{app}{os.pathsep}app",
            "--collect-data",
            "engine",
        ]
        for module in hidden_imports(spec, self.app_dir):
            cmd += ["--hidden-import", module]
        for module in excludes(spec):
            cmd += ["--exclude-module", module]
        cmd.append(str(Path(__file__).with_name("entry.py")))
        run("package", cmd, self.log)
        folder = self.work / "dist" / name
        self.report.sizes_mb["before_trim"] = folder_mb(folder)
        trim(folder / "_internal")
        self.report.sizes_mb["folder"] = folder_mb(folder)
        return folder / (f"{name}.exe" if sys.platform == "win32" else name)

    def _exe_run(
        self, stage: str, exe: Path, args: list[str], env: dict[str, str | None]
    ) -> dict[str, Any]:
        result = self.work / f"{stage}.json"
        env = {"MAKEMYEXE_DATA_DIR": str(self.work / "data"), **env}
        try:
            run(stage, [str(exe), *args, "--report", str(result)], self.log, env)
        except StageFailed as err:
            err.log_tail = _with_result(err.log_tail, _read_json(result))
            raise
        return _read_json(result)

    def _smoke_test(self, exe: Path) -> None:
        offscreen = {"QT_QPA_PLATFORM": "offscreen"}
        args = ["--smoke-test", "--out", str(self.work / "smoke-out")]
        report = self._exe_run("smoke_test", exe, args, offscreen)
        if report.get("status") != "passed":
            raise StageFailed("smoke_test", f"{exe.name} --smoke-test", _with_result("", report))

    def _launch_check(self, exe: Path) -> None:
        # The real platform plugin (qwindows on Windows), not offscreen.
        report = self._exe_run("launch_check", exe, ["--launch-check"], {"QT_QPA_PLATFORM": None})
        if report.get("status") != "passed":
            raise StageFailed("launch_check", f"{exe.name} --launch-check", json.dumps(report))

    def _guide(self, exe: Path, screens: Path) -> None:
        offscreen = {"QT_QPA_PLATFORM": "offscreen"}
        self._exe_run("guide", exe, ["--guide-mode", str(screens)], offscreen)
        if not (screens / "manifest.json").is_file():
            raise StageFailed("guide", f"{exe.name} --guide-mode", "no manifest.json written")

    def _guide_pdf(self, spec: AutomationSpec, screens: Path) -> Path:
        return make_guide(spec, screens, self.report.exe, self.out / "Guide.pdf")

    def _zip(self, folder: Path, guide: Path) -> Path:
        target = self.out / f"{folder.name}.zip"
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    archive.write(path, Path(folder.name) / path.relative_to(folder))
            archive.write(guide, Path(folder.name) / "Guide.pdf")
        self.report.sizes_mb["zip"] = round(target.stat().st_size / 1_000_000, 1)
        return target


def _with_result(log_tail: str, result: dict[str, Any]) -> str:
    """Put the app's own JSON result (the failing step, the error) in front of the log tail."""
    if not result:
        return log_tail
    text = json.dumps(result, indent=2)
    return (text + "\n" + log_tail)[:LOG_TAIL_BYTES]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m build.package", description=__doc__)
    parser.add_argument("app_dir", type=Path, help="folder with spec.json (automations/<id>)")
    parser.add_argument("--out", type=Path, default=Path("dist"))
    parser.add_argument(
        "--launch-check", action="store_true", help="also open the real window (needs a desktop)"
    )
    parser.add_argument(
        "--expect-spec-sha256", metavar="HEX", help="fail unless spec.json has this fingerprint"
    )
    args = parser.parse_args(argv)
    report = Packager(args.app_dir, args.out, args.launch_check, args.expect_spec_sha256).run()
    summary = {k: getattr(report, k) for k in ("status", "automation", "exe", "stage", "sizes_mb")}
    print(json.dumps(summary, indent=2))
    if report.status != "passed":
        print(f"\n{report.stage} failed: {report.command}\n{report.log_tail}", file=sys.stderr)
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
