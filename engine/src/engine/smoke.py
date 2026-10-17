"""Smoke test: run the real pipeline headless on sample_data. Used by the Windows build job."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from engine.changes import apply_plan, undo
from engine.context import RunContext
from engine.errors import EngineError, error_report
from engine.loader import LoadedSpec
from engine.runner import run
from engine.storage import Store
from engine.values import RenamePlan, SavedFile


def smoke_test(loaded: LoadedSpec, out_dir: Path | None = None) -> dict[str, Any]:
    """Run on copies of the sample files: apply planned renames, then undo them."""
    spec = loaded.spec
    with tempfile.TemporaryDirectory(prefix="makemyexe-smoke-") as tmp:
        workspace = Path(tmp) / "Sample files"
        store = Store(spec.id, root=Path(tmp) / "data")
        try:
            ctx = RunContext(
                spec=spec,
                inputs=loaded.sample_inputs(workspace),
                settings=loaded.sample_settings(workspace),
                store=store,
                output_dir=out_dir or Path(tmp) / "output",
                spec_dir=loaded.dir,
            )
            result = run(ctx)
            report: dict[str, Any] = {"status": "passed", "steps": len(spec.steps)}
            saved = result.last_value
            if isinstance(saved, SavedFile):
                report["output"] = {"file": saved.path.name, "bytes": saved.path.stat().st_size}
            for plan in result.pending:
                report["changes"] = _check_changes(plan, store, spec.title)
        except Exception as err:  # reported in the JSON, never raised
            return {"status": "failed", "report": error_report(err, spec.id, spec.version)}
        return report


def _check_changes(plan: RenamePlan, store: Store, title: str) -> dict[str, int]:
    """Apply the plan, check every file moved, undo, check every file is back."""
    batch = apply_plan(plan, store, f"{title}: smoke test")
    if not all(m.target.exists() and not m.source.exists() for m in plan.moves):
        raise EngineError("renamed files are not where the plan said")
    undone = undo(store, batch)
    if undone.skipped or not all(m.source.exists() for m in plan.moves):
        raise EngineError("undo did not restore every file")
    return {"renamed": len(plan.moves), "undo_restored": undone.restored}
