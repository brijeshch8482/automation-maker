"""python -m tools.validate_spec <file> [<file> ...]

Exit code 0 if every spec is valid, 1 otherwise. Issues are printed as `<path>: <message>`.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from tools.validate_spec import Issue, validate_spec


def check_file(path: Path) -> list[Issue]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as err:
        return [Issue("", f"cannot read file: {err.strerror or err}")]
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        return [Issue("", f"not valid JSON: {err}")]
    return validate_spec(data)[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.validate_spec", description="Validate AutomationSpec JSON files."
    )
    parser.add_argument("files", nargs="+", type=Path, metavar="file")
    args = parser.parse_args(argv)

    failed = False
    for path in args.files:
        issues = check_file(path)
        if issues:
            failed = True
            print(f"FAIL {path} ({len(issues)} issue{'s' if len(issues) != 1 else ''})")
            for issue in issues:
                print(f"  {issue}")
        else:
            print(f"OK   {path}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
