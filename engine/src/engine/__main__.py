"""Start an automation.

    python -m engine path/to/spec.json                  the app
    python -m engine spec.json --guide-mode out/        screenshots for the guide
    python -m engine spec.json --smoke-test [--out d/]  headless run on sample_data, JSON report
    python -m engine spec.json --launch-check           open the real window, then close it

In a packaged EXE the spec is bundled (app/spec.json) and the path may be left out. A windowed
EXE has no console, so --report FILE also writes the result as JSON for the build to read.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from engine.errors import EngineError
from engine.guards import block_network
from engine.loader import load_spec


def _default_spec() -> Path | None:
    if getattr(sys, "frozen", False):
        bundled = Path(getattr(sys, "_MEIPASS", "")) / "app" / "spec.json"
        return bundled if bundled.is_file() else Path(sys.executable).parent / "spec.json"
    return None


def write_report(path: Path | None, report: dict[str, Any]) -> None:
    if path is not None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, indent=2), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine", description=__doc__.split("\n\n")[0])
    parser.add_argument("spec", nargs="?", type=Path, default=_default_spec())
    parser.add_argument("--guide-mode", type=Path, metavar="OUT_DIR")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--out", type=Path, help="output folder for --smoke-test")
    parser.add_argument("--launch-check", action="store_true")
    parser.add_argument("--report", type=Path, metavar="FILE", help="also write the result here")
    args = parser.parse_args(argv)
    if args.spec is None:
        parser.error("give the path to spec.json")

    try:
        loaded = load_spec(args.spec)
    except EngineError as err:
        print(f"error: {err}", file=sys.stderr)
        write_report(args.report, {"status": "failed", "error": str(err)})
        return 2
    if not loaded.spec.network.required:
        block_network()

    if args.smoke_test:
        from engine.smoke import smoke_test

        report = smoke_test(loaded, args.out)
        print(json.dumps(report, indent=2))
        write_report(args.report, report)
        return 0 if report["status"] == "passed" else 1

    if args.guide_mode:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from engine.storage import Store
    from engine.ui.theme import apply_theme

    app = QApplication(sys.argv[:1])
    apply_theme(app)

    if args.guide_mode:
        from engine.ui.guide import GuideError, render_guide

        try:
            screens = render_guide(loaded, args.guide_mode)
        except GuideError as err:
            print(f"error: {err}", file=sys.stderr)
            write_report(args.report, {"status": "failed", "error": str(err)})
            return 1
        print(f"saved {len(screens)} screens to {args.guide_mode}")
        write_report(args.report, {"status": "passed", "screens": len(screens)})
        return 0

    if args.launch_check:
        return _launch_check(app, loaded, args.report)

    from engine.ui.window import MainWindow

    window = MainWindow(loaded, Store(loaded.spec.id))
    window.show()
    code = app.exec()
    # Destroy widgets before QApplication goes away; the other order crashes Qt at exit.
    window.deleteLater()
    del window
    app.processEvents()
    return code


def _launch_check(app: Any, loaded: Any, report_path: Path | None) -> int:
    """Open the main window on the real display (not offscreen) and close it again.

    Proves a packaged EXE finds its Qt platform plugin and DLLs. Settings go to a temp folder.
    """
    from PySide6.QtCore import QTimer

    from engine.storage import Store
    from engine.ui.window import MainWindow

    with tempfile.TemporaryDirectory() as data:
        window = MainWindow(loaded, Store(loaded.spec.id, root=Path(data)))
        window.show()
        shown: dict[str, Any] = {}

        def check() -> None:
            shown.update(visible=window.isVisible(), platform=app.platformName())
            app.quit()

        QTimer.singleShot(1500, check)
        app.exec()
        window.close()
        window.deleteLater()
        app.processEvents()
    passed = bool(shown.get("visible"))
    report = {"status": "passed" if passed else "failed", **shown}
    print(json.dumps(report))
    write_report(report_path, report)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
