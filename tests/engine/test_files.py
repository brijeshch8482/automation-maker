"""files.scan / files.rename, applying renames safely, and the undo log."""

import json
import os
import time
from pathlib import Path

import pytest

import engine.changes as changes
from engine.blocks import files
from engine.changes import TEMP_PREFIX, apply_plan, undo
from engine.errors import EngineError
from engine.loader import load_spec
from engine.storage import Store
from engine.ui.fields import compact_path
from spec.catalog import FilesRenameArgs, FilesScanArgs
from spec.validate import validate_spec
from tests.conftest import AUTOMATIONS_DIR

RENAME = AUTOMATIONS_DIR / "bulk-rename"


@pytest.fixture
def rename_spec():
    return load_spec(RENAME / "spec.json")


def make_files(folder: Path, *names: str) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    for name in names:
        (folder / name).write_text(f"content of {name}", encoding="utf-8")
    return folder


def contents(folder: Path) -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(folder.iterdir()) if p.is_file()}


def plan_for(make_ctx, rename_spec, folder, **inputs):
    values = {"folder": str(folder), "base_name": "Trip", "start_number": 1, **inputs}
    ctx = make_ctx(inputs=values, settings={}, loaded=rename_spec)
    listed = files.scan(ctx, FilesScanArgs(folder="folder"))
    ctx.outs["files"] = listed
    args = FilesRenameArgs(files="files", name="{base_name} {n}", start="start_number", pad=3)
    return files.rename(ctx, args), ctx


# --- files.scan ---------------------------------------------------------------------------


def test_scan_sorts_naturally_and_skips_hidden_temp_and_folders(make_ctx, rename_spec, tmp_path):
    folder = make_files(
        tmp_path / "f", "IMG_10.jpg", "IMG_2.jpg", "img_1.JPG", ".hidden", f"{TEMP_PREFIX}x.jpg"
    )
    (folder / "sub").mkdir()
    ctx = make_ctx(inputs={"folder": str(folder)}, settings={}, loaded=rename_spec)
    names = [f.path.name for f in files.scan(ctx, FilesScanArgs(folder="folder"))]
    assert names == ["img_1.JPG", "IMG_2.jpg", "IMG_10.jpg"]
    only_jpg = files.scan(ctx, FilesScanArgs(folder="folder", extensions=["jpg"]))
    assert len(only_jpg) == 3  # extension match ignores case


def test_scan_by_modified_and_missing_folder(make_ctx, rename_spec, tmp_path):
    folder = make_files(tmp_path / "f", "b.txt", "a.txt")
    now = time.time()
    os.utime(folder / "a.txt", (now, now))
    os.utime(folder / "b.txt", (now - 100, now - 100))
    ctx = make_ctx(inputs={"folder": str(folder)}, settings={}, loaded=rename_spec)
    by_date = files.scan(ctx, FilesScanArgs(folder="folder", sort="modified"))
    assert [f.path.name for f in by_date] == ["b.txt", "a.txt"]
    ctx = make_ctx(inputs={"folder": str(tmp_path / "nope")}, settings={}, loaded=rename_spec)
    with pytest.raises(EngineError, match="folder that exists"):
        files.scan(ctx, FilesScanArgs(folder="folder"))


# --- files.rename (planning only) ---------------------------------------------------------


def test_rename_plan_changes_nothing_on_disk(make_ctx, rename_spec, tmp_path):
    folder = make_files(tmp_path / "f", "IMG_1.jpg", "IMG_2.png", "notes")
    before = contents(folder)
    plan, ctx = plan_for(make_ctx, rename_spec, folder)
    assert [(m.source.name, m.target.name) for m in plan.moves] == [
        ("IMG_1.jpg", "Trip 001.jpg"),
        ("IMG_2.png", "Trip 002.png"),  # extension kept
        ("notes", "Trip 003"),  # no extension stays without one
    ]
    assert ctx.pending == [plan]
    assert contents(folder) == before


def test_rename_avoids_names_taken_by_other_files(make_ctx, rename_spec, tmp_path):
    folder = make_files(tmp_path / "f", "a.jpg", "b.jpg")
    make_files(folder, "readme.TXT")  # not renamed itself? it is: every file is in the batch
    plan, _ = plan_for(make_ctx, rename_spec, folder, base_name="readme", start_number="")
    # start '' -> 1; three files want "readme 001..003" with pad 3: no clash
    assert len(plan.moves) == 3
    other = make_files(tmp_path / "g", "x.jpg", "y.jpg")
    (other / "sub").mkdir()
    ctx = make_ctx(
        inputs={"folder": str(other), "base_name": "Same", "start_number": 1},
        settings={},
        loaded=rename_spec,
    )
    ctx.outs["files"] = files.scan(ctx, FilesScanArgs(folder="folder"))
    # A pattern without {n} gives every file the same name: the 2nd gets " (2)".
    plan = files.rename(ctx, FilesRenameArgs(files="files", name="{base_name}"))
    assert [m.target.name for m in plan.moves] == ["Same.jpg", "Same (2).jpg"]
    assert plan.adjusted == 1


def test_rename_respects_files_that_are_not_renamed(make_ctx, rename_spec, tmp_path):
    folder = make_files(tmp_path / "f", "a.jpg", "TRIP 001.JPG")
    ctx = make_ctx(
        inputs={"folder": str(folder), "base_name": "Trip", "start_number": 1},
        settings={},
        loaded=rename_spec,
    )
    ctx.outs["files"] = [
        f for f in files.scan(ctx, FilesScanArgs(folder="folder")) if f.path.name == "a.jpg"
    ]
    plan = files.rename(
        ctx, FilesRenameArgs(files="files", name="{base_name} {n}", start="start_number", pad=3)
    )
    # "TRIP 001.JPG" stays and Windows ignores case, so the new name must differ.
    assert [m.target.name for m in plan.moves] == ["Trip 001 (2).jpg"]


def test_rename_unchanged_per_item_vars_and_safe_names(make_ctx, rename_spec, tmp_path):
    folder = make_files(tmp_path / "f", "Trip 001.jpg", "zebra.jpg")  # sorts after "Trip"
    plan, _ = plan_for(make_ctx, rename_spec, folder)
    assert plan.unchanged == 1
    assert [m.target.name for m in plan.moves] == ["Trip 002.jpg"]
    ctx = make_ctx(
        inputs={"folder": str(folder), "base_name": "a/b:c", "start_number": 7},
        settings={},
        loaded=rename_spec,
    )
    ctx.outs["files"] = files.scan(ctx, FilesScanArgs(folder="folder"))
    plan = files.rename(
        ctx,
        FilesRenameArgs(files="files", name="{base_name} {name} {date} {n}", start="start_number"),
    )
    target = plan.moves[0].target.name
    assert target.startswith("a-b-c Trip 001 ") and target.endswith(" 7.jpg")
    assert "/" not in target and ":" not in target


def test_rename_errors(make_ctx, rename_spec, tmp_path):
    folder = make_files(tmp_path / "f", "a.jpg")
    with pytest.raises(EngineError, match="whole number"):
        plan_for(make_ctx, rename_spec, folder, start_number="1.5")
    with pytest.raises(EngineError, match="not a number"):
        plan_for(make_ctx, rename_spec, folder, start_number="abc")
    ctx = make_ctx(
        inputs={"folder": str(folder), "base_name": " "}, settings={}, loaded=rename_spec
    )
    ctx.outs["files"] = files.scan(ctx, FilesScanArgs(folder="folder"))
    with pytest.raises(EngineError, match="empty name"):
        files.rename(ctx, FilesRenameArgs(files="files", name="{base_name}"))
    empty = make_files(tmp_path / "empty")
    with pytest.raises(EngineError, match="no matching files"):
        plan_for(make_ctx, rename_spec, empty)


# --- applying and undoing -----------------------------------------------------------------


def test_apply_then_undo_round_trip(make_ctx, rename_spec, tmp_path, store):
    folder = make_files(tmp_path / "f", "IMG_1.jpg", "IMG_2.jpg")
    before = contents(folder)
    plan, _ = plan_for(make_ctx, rename_spec, folder)
    batch = apply_plan(plan, store, "test")
    after = contents(folder)
    assert after == {"Trip 001.jpg": "content of IMG_1.jpg", "Trip 002.jpg": "content of IMG_2.jpg"}
    assert store.batch(batch)[0] == "done"
    assert undo(store, batch).restored == 2
    assert contents(folder) == before
    assert store.batch(batch)[0] == "undone"
    with pytest.raises(EngineError, match="nothing to undo"):
        undo(store, batch)


def test_swap_and_case_only_renames(make_ctx, rename_spec, tmp_path, store):
    folder = make_files(tmp_path / "f", "Trip 002.jpg", "Trip 001.jpg")
    ctx = make_ctx(inputs={"folder": str(folder)}, settings={}, loaded=rename_spec)
    listed = files.scan(ctx, FilesScanArgs(folder="folder"))
    ctx.outs["files"] = list(reversed(listed))  # 002 first -> becomes 001: a swap
    plan = files.rename(ctx, FilesRenameArgs(files="files", name="Trip {n}", pad=3))
    apply_plan(plan, store, "swap")
    assert contents(folder) == {
        "Trip 001.jpg": "content of Trip 002.jpg",
        "Trip 002.jpg": "content of Trip 001.jpg",
    }

    lower = make_files(tmp_path / "g", "photo.jpg")
    ctx = make_ctx(inputs={"folder": str(lower)}, settings={}, loaded=rename_spec)
    ctx.outs["files"] = files.scan(ctx, FilesScanArgs(folder="folder"))
    plan = files.rename(ctx, FilesRenameArgs(files="files", name="PHOTO"))
    apply_plan(plan, store, "case")
    assert [p.name for p in lower.iterdir()] == ["PHOTO.jpg"]


def test_a_file_that_appears_after_the_preview_is_never_overwritten(
    make_ctx, rename_spec, tmp_path, store
):
    folder = make_files(tmp_path / "f", "a.jpg", "b.jpg")
    plan, _ = plan_for(make_ctx, rename_spec, folder)
    (folder / "Trip 002.jpg").write_text("someone else's file", encoding="utf-8")
    with pytest.raises(EngineError, match="Nothing was changed"):
        apply_plan(plan, store, "late clash")
    assert contents(folder) == {
        "Trip 002.jpg": "someone else's file",
        "a.jpg": "content of a.jpg",
        "b.jpg": "content of b.jpg",
    }
    assert not any(p.name.startswith(TEMP_PREFIX) for p in folder.iterdir())


def test_failure_halfway_rolls_everything_back(make_ctx, rename_spec, tmp_path, store, monkeypatch):
    folder = make_files(tmp_path / "f", "a.jpg", "b.jpg", "c.jpg")
    before = contents(folder)
    plan, _ = plan_for(make_ctx, rename_spec, folder)
    real_rename, calls = os.rename, {"n": 0}

    def flaky_rename(src, dst):
        calls["n"] += 1
        if calls["n"] == 5:  # in phase 2, after some files already have new names
            raise PermissionError("file is open in another program")
        real_rename(src, dst)

    monkeypatch.setattr(changes.os, "rename", flaky_rename)
    with pytest.raises(EngineError):
        apply_plan(plan, store, "flaky")
    monkeypatch.setattr(changes.os, "rename", real_rename)
    assert contents(folder) == before


def test_undo_never_overwrites_a_file_that_took_the_old_name(
    make_ctx, rename_spec, tmp_path, store
):
    folder = make_files(tmp_path / "f", "a.jpg", "b.jpg")
    plan, _ = plan_for(make_ctx, rename_spec, folder)
    batch = apply_plan(plan, store, "test")
    (folder / "a.jpg").write_text("new file using the old name", encoding="utf-8")
    result = undo(store, batch)
    assert (result.restored, result.skipped) == (1, 1)
    assert contents(folder) == {
        "Trip 001.jpg": "content of a.jpg",
        "a.jpg": "new file using the old name",
        "b.jpg": "content of b.jpg",
    }


def test_undo_log_is_written_before_files_move(make_ctx, rename_spec, tmp_path, store, monkeypatch):
    folder = make_files(tmp_path / "f", "a.jpg")
    plan, _ = plan_for(make_ctx, rename_spec, folder)
    seen = []

    def spy(moves):
        seen.append(Store("invoice-generator", root=store.dir.parent).batch(1))
        raise EngineError("stop")

    monkeypatch.setattr(changes, "_two_phase", spy)
    with pytest.raises(EngineError):
        apply_plan(plan, store, "spy")
    status, moves = seen[0]
    assert status == "pending" and moves == [(str(folder / "a.jpg"), str(folder / "Trip 001.jpg"))]
    assert store.batch(1)[0] == "failed"


# --- samples, catalog and display --------------------------------------------------------


def test_sample_files_are_copied_to_a_workspace(rename_spec, tmp_path):
    original = sorted(p.name for p in (RENAME / "samples" / "Holiday photos").iterdir())
    inputs = rename_spec.sample_inputs(tmp_path / "ws")
    assert inputs["folder"] == str(tmp_path / "ws" / "Holiday photos")
    assert sorted(p.name for p in Path(inputs["folder"]).iterdir()) == original
    assert rename_spec.sample_inputs()["folder"] == str(RENAME / "samples" / "Holiday photos")


def test_sample_paths_must_stay_next_to_the_spec(tmp_path):
    spec = json.loads((RENAME / "spec.json").read_text(encoding="utf-8"))
    for bad, message in (("../elsewhere", "without '..'"), ("samples/missing", "missing")):
        spec["sample_data"]["folder"] = bad
        path = tmp_path / bad.replace("/", "_") / "spec.json"
        path.parent.mkdir()
        path.write_text(json.dumps(spec), encoding="utf-8")
        with pytest.raises(EngineError, match=message):
            load_spec(path).sample_inputs()


def test_rename_template_validation():
    spec = json.loads((RENAME / "spec.json").read_text(encoding="utf-8"))
    spec["steps"][1]["args"]["name"] = "{base_name} {n} {name} {date}"
    assert validate_spec(spec)[1] == []
    spec["steps"][1]["args"]["name"] = "{base_name} {number}"
    issues = [str(i) for i in validate_spec(spec)[1]]
    assert issues == [
        "steps[1].args.name: {number} is not an input key or the out of an earlier step"
    ]


def test_compact_path():
    assert compact_path("") == ""
    assert compact_path("/a/b") == "/a/b"
    assert compact_path(str(Path("/home/me/Documents/Holiday photos"))) == os.sep.join(
        ["…", "Documents", "Holiday photos"]
    )
