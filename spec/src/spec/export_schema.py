"""Export JSON Schema for the AutomationSpec and the block catalog.

python -m spec.export_schema           # write spec/schema/*.json
python -m spec.export_schema --check   # fail if the committed files are stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from spec.catalog import catalog_json_schema
from spec.models import AutomationSpec

SCHEMA_DIR = Path(__file__).resolve().parents[2] / "schema"
SCHEMA_ID = "https://makemyexe.com/schema/automation_spec.schema.json"


def automation_spec_schema() -> dict[str, Any]:
    schema = AutomationSpec.model_json_schema()
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": SCHEMA_ID, **schema}


def rendered_files() -> dict[str, str]:
    """File name -> exact file content."""
    return {
        "automation_spec.schema.json": _dump(automation_spec_schema()),
        "block_catalog.json": _dump(catalog_json_schema()),
    }


def _dump(data: dict[str, Any]) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m spec.export_schema", description=__doc__)
    parser.add_argument("--out", type=Path, default=SCHEMA_DIR, help="output directory")
    parser.add_argument("--check", action="store_true", help="only check files are up to date")
    args = parser.parse_args(argv)

    stale = []
    for name, content in rendered_files().items():
        path = args.out / name
        current = path.read_text(encoding="utf-8") if path.exists() else None
        if current == content:
            continue
        if args.check:
            stale.append(path)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8", newline="\n")
            print(f"wrote {path}")

    if stale:
        for path in stale:
            print(f"stale: {path} (run `python -m spec.export_schema`)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
