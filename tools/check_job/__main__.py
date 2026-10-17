"""python -m tools.check_job jobs/<id> [--json]

Exit code 0 when every check passed, 1 otherwise. See tools/check_job/__init__.py.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.check_job import check_job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.check_job", description="Check a generated job folder."
    )
    parser.add_argument("folder", type=Path, help="jobs/<id> (or automations/<id>)")
    parser.add_argument("--json", action="store_true", help="print the report as JSON")
    args = parser.parse_args(argv)

    report = check_job(args.folder)
    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        for check in report.checks:
            print(f"{check.status.upper():7} {check.name}")
            for problem in check.problems:
                print(f"        {problem}")
            if check.status == "failed" and check.command:
                print(f"        command: {check.command}")
            if check.log_tail:
                print("\n".join("        | " + line for line in check.log_tail.splitlines()))
        custom = "with a custom step" if report.used_custom_step else "blocks only"
        print(f"\n{report.status.upper()} {report.folder} ({custom})")
    return 0 if report.status == "passed" else 1


if __name__ == "__main__":
    sys.exit(main())
