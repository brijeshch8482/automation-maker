"""Start an automation.

    python -m engine path/to/spec.json                  the app
    python -m engine spec.json --guide-mode out/        screenshots for the guide
    python -m engine spec.json --smoke-test [--out d/]  headless run on sample_data, JSON report

In a packaged EXE, spec.json sits next to the executable and the path may be left out.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from engine.errors import EngineError
from engine.guards import block_network
from engine.loader import load_spec


def _default_spec() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "spec.json"
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m engine", description=__doc__.split("\n\n")[0])
    parser.add_argument("spec", nargs="?", type=Path, default=_default_spec())
    parser.add_argument("--guide-mode", type=Path, metavar="OUT_DIR")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--out", type=Path, help="output folder for --smoke-test")
    args = parser.parse_args(argv)
    if args.spec is None:
        parser.error("give the path to spec.json")

    try:
        loaded = load_spec(args.spec)
    except EngineError as err:
        print(f"error: {err}", file=sys.stderr)
        return 2
    if not loaded.spec.network.required:
        block_network()

    if args.smoke_test:
        from engine.smoke import smoke_test

        report = smoke_test(loaded, args.out)
        print(json.dumps(report, indent=2))
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
            return 1
        print(f"saved {len(screens)} screens to {args.guide_mode}")
        return 0

    from engine.ui.window import MainWindow

    window = MainWindow(loaded, Store(loaded.spec.id))
    window.show()
    code = app.exec()
    # Destroy widgets before QApplication goes away; the other order crashes Qt at exit.
    window.deleteLater()
    del window
    app.processEvents()
    return code


if __name__ == "__main__":
    sys.exit(main())
