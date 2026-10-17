"""Guide mode: render every screen with the spec's sample_data (ARCHITECTURE.md §8).

Writes PNGs plus manifest.json (file names and captions) for the Guide.pdf builder, and a copy of
what the sample run produced. Runs against a throwaway data folder, so nothing persists.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QApplication

from engine.loader import LoadedSpec
from engine.storage import Store, default_output_dir
from engine.ui.window import MainWindow
from engine.values import SavedFile


class GuideError(Exception):
    pass


def _grab(window: MainWindow, path: Path) -> None:
    QApplication.processEvents()
    if not window.grab().save(str(path)):
        raise GuideError(f"could not save {path.name}")


def render_guide(loaded: LoadedSpec, out_dir: Path) -> list[dict[str, Any]]:
    out_dir.mkdir(parents=True, exist_ok=True)
    spec = loaded.spec
    screens: list[dict[str, Any]] = []

    def shot(name: str, caption: str) -> None:
        _grab(window, out_dir / name)
        screens.append({"file": name, "caption": caption})

    with tempfile.TemporaryDirectory(prefix="makemyexe-guide-") as tmp:
        store = Store(spec.id, root=Path(tmp) / "data")
        window = MainWindow(
            loaded,
            store,
            inputs=loaded.sample_inputs(),
            # Same folder name as the app's default (Documents\MakeMyEXE\<title>).
            output_dir=Path(tmp) / default_output_dir(spec.title).name,
            open_results=False,
        )
        window.show()

        if spec.settings:
            window.show_page(window.setup_page)
            for key, value in loaded.sample_settings().items():
                window.settings_form.widgets[key].set_value(value)
            shot("01-setup.png", "The first time, enter your details. They are saved on this PC.")
            if not window._save_settings():
                raise GuideError("sample_data does not fill the required settings")

        shot("02-fill-in.png", "Fill in the form. Required fields are marked with *.")
        result = window.run()
        if result is None:
            raise GuideError(f"the sample run failed: {window.last_error!r}")
        shot("03-result.png", "Press Run. Your result is saved as a new file; open it from here.")
        if isinstance(result.last_value, SavedFile):
            shutil.copy(
                result.last_value.path, out_dir / f"sample-output{result.last_value.path.suffix}"
            )

        required = next((f for f in spec.inputs if f.required), None)
        if required is not None:
            window.show_page(window.run_page)
            window.inputs_form.widgets[required.key].set_value(None)
            window.run()
            shot(
                "04-check-fields.png",
                "If something is missing, the field is highlighted. Nothing runs until it's fixed.",
            )
        window.close()

    (out_dir / "manifest.json").write_text(
        json.dumps({"automation": spec.id, "version": spec.version, "screens": screens}, indent=2),
        encoding="utf-8",
    )
    return screens
