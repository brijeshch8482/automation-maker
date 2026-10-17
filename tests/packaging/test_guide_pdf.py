"""Guide.pdf from guide-mode screenshots."""

import json
import shutil

import pytest
from pypdf import PdfReader

from build.guide_pdf import GuideError, make_guide
from engine.loader import load_spec
from tests.conftest import AUTOMATIONS_DIR, REPO_ROOT

SCREENS = REPO_ROOT / "docs" / "screenshots"


def text_of(path) -> str:
    return " ".join(page.extract_text() for page in PdfReader(path).pages)


def test_guide_has_start_data_and_every_step(tmp_path):
    spec = load_spec(AUTOMATIONS_DIR / "make-pdf" / "spec.json").spec
    out = make_guide(spec, SCREENS / "make-pdf", "MakePDF", tmp_path / "Guide.pdf")
    reader = PdfReader(out)
    assert len(reader.pages) == 3  # start page + two steps per page
    text = text_of(out)
    for expected in ("Make PDF", "Double-click MakePDF.exe", "Run anyway", "never connects"):
        assert expected in text
    assert "MakeMyEXE\\make-pdf" in text
    manifest = json.loads((SCREENS / "make-pdf" / "manifest.json").read_text())
    assert text.count("STEP") == len(manifest["screens"])
    assert sum(len(page.images) for page in reader.pages) == len(manifest["screens"])


def test_file_changing_apps_promise_preview_and_undo(tmp_path):
    spec = load_spec(AUTOMATIONS_DIR / "bulk-rename" / "spec.json").spec
    text = text_of(make_guide(spec, SCREENS / "bulk-rename", "BulkRename", tmp_path / "g.pdf"))
    assert "renamed only after you check a preview" in text
    assert "never changed" not in text


def test_missing_screenshots(tmp_path):
    spec = load_spec(AUTOMATIONS_DIR / "make-pdf" / "spec.json").spec
    with pytest.raises(GuideError, match="missing"):
        make_guide(spec, tmp_path, "MakePDF", tmp_path / "g.pdf")
    shutil.copy(SCREENS / "make-pdf" / "manifest.json", tmp_path)
    with pytest.raises(GuideError, match=r"01-setup\.png is missing"):
        make_guide(spec, tmp_path, "MakePDF", tmp_path / "g.pdf")
