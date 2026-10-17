"""Smoke test: run the real pipeline headless on sample_data. Used by the Windows build job."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from engine.context import RunContext
from engine.errors import error_report
from engine.loader import LoadedSpec
from engine.runner import run
from engine.storage import Store
from engine.values import SavedFile


def smoke_test(loaded: LoadedSpec, out_dir: Path | None = None) -> dict[str, Any]:
    spec = loaded.spec
    with tempfile.TemporaryDirectory(prefix="makemyexe-smoke-") as tmp:
        ctx = RunContext(
            spec=spec,
            inputs=loaded.sample_inputs(),
            settings=loaded.sample_settings(),
            store=Store(spec.id, root=Path(tmp) / "data"),
            output_dir=out_dir or Path(tmp) / "output",
            spec_dir=loaded.dir,
        )
        try:
            result = run(ctx)
        except Exception as err:  # reported in the JSON, never raised
            return {"status": "failed", "report": error_report(err, spec.id, spec.version)}
        saved = result.last_value
        output: dict[str, Any] = {}
        if isinstance(saved, SavedFile):
            output = {"file": saved.path.name, "bytes": saved.path.stat().st_size}
        return {"status": "passed", "steps": len(spec.steps), "output": output}
