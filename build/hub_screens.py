"""Screenshots of the Hub (docs/screenshots/hub/), rendered offscreen with QWidget.grab().

    uv run python -m build.hub_screens --out docs/screenshots/hub

Uses the catalog automations, signed with a throwaway key into a temporary store, so it needs
no secrets and leaves nothing behind. Same code path as the app: HubWindow over an AppStore.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

from build import pack as build_pack

REPO_ROOT = Path(__file__).resolve().parents[1]
CATALOG = ["bulk-rename", "invoice-generator", "make-pdf", "pdf-merge"]


def _pack(source: Path, work: Path, pem: str, version: str | None = None) -> Path:
    app = work / f"{source.name}-{version or 'base'}"
    shutil.copytree(source, app)
    if version:
        spec = json.loads((app / "spec.json").read_text(encoding="utf-8"))
        spec["version"] = version
        (app / "spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")
    return build_pack.make_pack(app, app / "out", "catalog", "screens-1", pem, "1.0.0")


def render(out: Path) -> list[str]:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication, QWidget

    from engine.store import AppStore
    from engine.ui.hub import HubWindow, ImportDialog
    from engine.ui.theme import apply_theme

    app = QApplication.instance() or QApplication(sys.argv[:1])
    apply_theme(app)
    out.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []

    def shot(widget: QWidget, name: str) -> None:
        widget.show()
        for _ in range(3):
            app.processEvents()
        widget.grab().save(str(out / name))
        saved.append(name)

    with tempfile.TemporaryDirectory(prefix="makemyexe-hub-") as tmp:
        work = Path(tmp)
        private, public = build_pack.keygen("screens-1", work / "keys")
        pem = private.read_text(encoding="utf-8")
        store = AppStore(work / "store", {"screens-1": bytes.fromhex(public)})
        plans = []
        window = HubWindow(
            store,
            confirm=lambda plan: plans.append(plan) or True,
            launcher=lambda *_: None,
            open_url=lambda _: None,
        )
        shot(window, "01-empty.png")

        packs = {name: _pack(REPO_ROOT / "automations" / name, work, pem) for name in CATALOG}
        dialog = ImportDialog(store_plan(store, packs["make-pdf"]))
        shot(dialog, "03-add.png")
        dialog.close()
        for name in CATALOG:
            store.import_bundle(packs[name])
        newer = _pack(REPO_ROOT / "automations" / "invoice-generator", work, pem, "1.1.0")
        window.import_path(newer)
        window.notice.hide()
        window.refresh()
        shot(window, "02-hub.png")

        dialog = ImportDialog(plans[-1])
        shot(dialog, "04-update.png")
        dialog.close()
        older = _pack(REPO_ROOT / "automations" / "invoice-generator", work, pem, "0.9.0")
        dialog = ImportDialog(store_plan(store, older))
        shot(dialog, "05-older-version.png")
        dialog.close()

        window.import_path(packs["pdf-merge"])
        shot(window, "06-added.png")
        tampered = work / "Changed.mmx"
        tampered.write_bytes(packs["make-pdf"].read_bytes()[:-40] + b"\0" * 40)
        window.import_path(tampered)
        shot(window, "07-refused.png")

        spec = store.automations_dir / "bulk-rename" / "1.0.0" / "spec.json"
        spec.write_text(spec.read_text(encoding="utf-8") + " ", encoding="utf-8")
        window.notice.hide()
        window.refresh()
        shot(window, "08-damaged.png")
        window.close()
    return saved


def store_plan(store, pack: Path):
    """The plan the confirmation would show for this file, without importing it."""
    plans = []
    store.import_bundle(pack, confirm=lambda plan: plans.append(plan) and False)
    return plans[0]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m build.hub_screens", description=__doc__)
    parser.add_argument("--out", type=Path, default=REPO_ROOT / "docs" / "screenshots" / "hub")
    args = parser.parse_args(argv)
    for name in render(args.out):
        print(args.out / name)
    return 0


if __name__ == "__main__":
    sys.exit(main())
