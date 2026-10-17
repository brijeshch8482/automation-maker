"""PyInstaller entry point of every packaged automation.

A windowed EXE has no console. In the automated modes (smoke test, guide, launch check) an
unexpected error must not open a dialog that blocks the build machine: it goes to --report.
"""

import json
import sys
import traceback
from pathlib import Path

AUTOMATED = ("--smoke-test", "--guide-mode", "--launch-check")


def _report_path(argv: list[str]) -> Path | None:
    if "--report" in argv and argv.index("--report") + 1 < len(argv):
        return Path(argv[argv.index("--report") + 1])
    return None


if __name__ == "__main__":
    argv = sys.argv[1:]
    try:
        from engine.__main__ import main

        sys.exit(main(argv))
    except SystemExit:
        raise
    except BaseException:
        if not any(flag in argv for flag in AUTOMATED):
            raise
        report = _report_path(argv)
        if report is not None:
            failure = {"status": "failed", "traceback": traceback.format_exc()[-6000:]}
            report.write_text(json.dumps(failure, indent=2), encoding="utf-8")
        sys.exit(3)
