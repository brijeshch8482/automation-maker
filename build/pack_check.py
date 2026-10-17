"""Check an app on Linux and make its guide: Pack Job 1 (docs/ARCHITECTURE.md §9).

    python -m build.pack_check <app_dir> --out <dir> [--expect-spec-sha256 HEX]

Stages: validate (+ the confirmed spec's fingerprint), check_job (layout, code rules, ruff,
bandit, the job's tests, smoke test; its result in a routine session is not trusted, so it
runs again here), guide (every screen offscreen on sample_data) and guide_pdf. Writes
<out>/Guide.pdf and <out>/report.json (same failure shape as build.package, which the repair
routine reads); exit 0 when every stage passed.

Generated code runs here, so this job never has secrets. The pack itself is made and signed
afterwards by build/pack.py in a job that reads the app folder from the pinned commit.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from pathlib import Path

from build.guide_pdf import make_guide
from build.package import LOG_TAIL_BYTES, Report, StageFailed, engine_version, exe_name, run
from spec.fingerprint import spec_sha256
from spec.validate import validate_spec
from tools.check_job import check_job


class PackCheck:
    def __init__(self, app_dir: Path, out: Path, expect_spec_sha256: str | None) -> None:
        self.app_dir = app_dir.resolve()
        self.out = out.resolve()
        self.work = self.out / "work"
        self.log = self.work / "build.log"
        self.expect = expect_spec_sha256
        self.report = Report(engine_version=engine_version())

    def run(self) -> Report:
        if self.out.exists():
            shutil.rmtree(self.out)
        self.work.mkdir(parents=True)
        try:
            spec = self._stage("validate", self._validate)
            self._stage("check_job", self._check_job)
            screens = self.out / "screenshots"
            self._stage("guide", lambda: self._guide(screens))
            guide = self.out / "Guide.pdf"
            self._stage("guide_pdf", lambda: make_guide(spec, screens, self.report.exe, guide))
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
            raise StageFailed(name, f"build.pack_check ({name})", detail) from err
        finally:
            seconds = round(time.monotonic() - started, 1)
            self.report.stages.append({"name": name, "seconds": seconds})

    def _validate(self):
        command = "python -m tools.validate_spec spec.json"
        try:
            data = json.loads((self.app_dir / "spec.json").read_text(encoding="utf-8"))
        except (OSError, ValueError) as err:
            raise StageFailed("validate", command, f"spec.json could not be read: {err}") from err
        if self.expect and spec_sha256(data) != self.expect.lower():
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

    def _check_job(self) -> None:
        result = check_job(self.app_dir)
        if result.status == "passed":
            return
        failed = next(c for c in result.checks if c.status == "failed")
        detail = "\n".join([*failed.problems, failed.log_tail or ""]).strip()
        raise StageFailed(
            "smoke_test" if failed.name == "smoke_test" else "check_job",
            failed.command or f"python -m tools.check_job ({failed.name})",
            detail[-LOG_TAIL_BYTES:],
            test=failed.name,
        )

    def _guide(self, screens: Path) -> None:
        env = {
            "QT_QPA_PLATFORM": "offscreen",
            "MAKEMYEXE_DATA_DIR": str(self.work / "data"),
            "PYTHONDONTWRITEBYTECODE": "1",
        }
        cmd = [sys.executable, "-m", "engine", str(self.app_dir / "spec.json")]
        run("guide", [*cmd, "--guide-mode", str(screens)], self.log, env)
        if not (screens / "manifest.json").is_file():
            raise StageFailed("guide", "python -m engine --guide-mode", "no manifest.json written")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m build.pack_check", description=__doc__)
    parser.add_argument("app_dir", type=Path)
    parser.add_argument("--out", type=Path, default=Path("dist"))
    parser.add_argument("--expect-spec-sha256", metavar="HEX")
    args = parser.parse_args(argv)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    report = PackCheck(args.app_dir, args.out, args.expect_spec_sha256).run()
    print(json.dumps({k: getattr(report, k) for k in ("status", "automation", "stage")}, indent=2))
    if report.status != "passed":
        print(f"\n{report.stage} failed: {report.command}\n{report.log_tail}", file=sys.stderr)
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
