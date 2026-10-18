"""Hub mode, Run mode and shortcuts (engine/hub.py, engine/ui/hub.py, engine/shortcuts.py)."""

import json
import os
import shutil
import struct
import subprocess
import sys
import textwrap

import pytest

from build import pack as build_pack
from engine import __main__ as cli
from engine import hub, shortcuts
from engine.store import AppStore
from tests.bundles import APP, make_bundle, make_layer, make_pack
from tests.conftest import REPO_ROOT

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl CLI")


@pytest.fixture(scope="module")
def key(tmp_path_factory):
    private, public = build_pack.keygen("test-1", tmp_path_factory.mktemp("keys"))
    return private.read_text(), bytes.fromhex(public)


@pytest.fixture
def store(tmp_path, key):
    return AppStore(tmp_path / "MakeMyEXE", {"test-1": key[1]})


@pytest.fixture
def env_store(tmp_path, key, monkeypatch):
    """The store and keys a CLI run finds through the environment, like the installed app."""
    keys = tmp_path / "keys.json"
    keys.write_text(json.dumps({"test-1": key[1].hex()}), encoding="utf-8")
    monkeypatch.setenv("MAKEMYEXE_STORE_DIR", str(tmp_path / "MakeMyEXE"))
    monkeypatch.setenv("MAKEMYEXE_TRUSTED_KEYS", str(keys))
    return AppStore(tmp_path / "MakeMyEXE", {"test-1": key[1]})


# --- MakeMyEXE ID -------------------------------------------------------------------------------


def test_display_id():
    shown = hub.display_id("0123456789abcdef0123456789abcdef")
    assert shown == hub.display_id("0123456789abcdef0123456789abcdef")
    assert len(shown) == len("MMX-XXXX-XXXX-XXXX") and shown.startswith("MMX-")
    assert all(c in hub.CROCKFORD for c in shown[4:].replace("-", ""))
    assert hub.display_id("f" * 32) != hub.display_id("e" + "f" * 31)


# --- list, pre-installed set, launching ----------------------------------------------------------


def test_entries_show_each_automation_and_damage(store, tmp_path, key):
    store.import_bundle(make_pack(tmp_path, key, "1.0.0"))
    store.import_bundle(make_pack(tmp_path, key, "1.1.0"))
    store.import_bundle(make_pack(tmp_path, key, app_id="other-app"))
    (entry, _other) = sorted(hub.entries(store), key=lambda e: e.id != APP)
    assert (entry.id, entry.version, entry.versions) == (APP, "1.1.0", ["1.1.0", "1.0.0"])
    assert entry.title and entry.problem is None and entry.network_domains == []
    spec = store.automations_dir / "other-app" / "1.0.0" / "spec.json"
    spec.write_text(spec.read_text(encoding="utf-8").replace("Count", "Kount"), encoding="utf-8")
    damaged = next(e for e in hub.entries(store) if e.id == "other-app")
    assert "changed after it was added" in damaged.problem


def test_preinstalled_set_adds_only_missing_or_newer(store, tmp_path, key):
    folder = tmp_path / "preinstalled"
    folder.mkdir()
    shutil.copy(make_pack(tmp_path, key, "1.1.0"), folder / "word-count.mmx")
    (folder / "broken.mmx").write_bytes(b"not a zip")
    assert [r.imported for r in hub.start_hub(store, folder)] == [True]
    assert [r.imported for r in hub.start_hub(store, folder)] == [False]  # already there
    store.import_bundle(make_pack(tmp_path, key, "1.2.0"))
    shutil.copy(make_pack(tmp_path, key, "1.0.0"), folder / "word-count.mmx")
    assert [r.imported for r in hub.start_hub(store, folder)] == [False]  # never downgrades
    assert store.installed() == {APP: ["1.2.0", "1.1.0"]}
    assert hub.start_hub(store, None) == []


def test_launch_command(monkeypatch):
    assert hub.launch_command(APP) == [sys.executable, "-m", "engine", "--run", APP]
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\Apps\MakeMyEXE\MakeMyEXE.exe")
    assert hub.launch_command(APP, "1.0.0") == [sys.executable, "--run", f"{APP}@1.0.0"]


# --- Run mode -----------------------------------------------------------------------------------


def test_run_mode_smoke_test_from_the_store(env_store, tmp_path, key, capsys):
    env_store.import_bundle(make_pack(tmp_path, key))
    assert cli.main(["--run", APP, "--smoke-test", "--out", str(tmp_path / "out")]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "passed"
    assert cli.main(["--run", f"{APP}@1.0.0", "--smoke-test"]) == 0
    assert cli.main(["--run", "missing-app", "--smoke-test"]) == 2
    assert "isn't installed" in capsys.readouterr().err


def test_run_mode_refuses_a_changed_install(env_store, tmp_path, key, capsys):
    env_store.import_bundle(make_pack(tmp_path, key))
    step = env_store.automations_dir / APP / "1.0.0" / "custom_step.py"
    step.write_bytes(step.read_bytes() + b"\n# changed\n")
    assert cli.main(["--run", APP, "--smoke-test"]) == 2
    assert "was changed" in capsys.readouterr().err


def test_each_automation_gets_only_its_own_layers(env_store, tmp_path, key, monkeypatch):
    one, pin_one = make_layer(tmp_path / "a", "tinylib-1.0")
    two, pin_two = make_layer(tmp_path / "b", "otherlib-2.0", b"VALUE = 2\n")
    pack_one = make_pack(tmp_path, key, layers=[pin_one])
    pack_two = make_pack(tmp_path, key, layers=[pin_two], app_id="other-app")
    env_store.import_bundle(make_bundle(tmp_path / "a.mmx", [pack_one], [one]))
    env_store.import_bundle(make_bundle(tmp_path / "b.mmx", [pack_two], [two]))
    monkeypatch.setattr(sys, "path", list(sys.path))
    cli._load_installed("other-app")
    libs = [p for p in sys.path if str(env_store.libs_dir) in p]
    assert libs == [str(env_store.libs_dir / "otherlib-2.0")]


# --- the no-network rule ----------------------------------------------------------------------


def test_the_hub_process_never_opens_a_socket(env_store, tmp_path, key):
    """A whole Hub start in a fresh process: tidy-up, pre-installed check, list, an import with a
    layer, the window. An audit hook records every socket operation Python sees."""
    preinstalled = tmp_path / "preinstalled"  # only found next to a frozen exe; checked above
    layer_dir, pin = make_layer(tmp_path / "src")
    bundle = make_bundle(tmp_path / "b.mmx", [make_pack(tmp_path, key, layers=[pin])], [layer_dir])
    env_store.import_bundle(make_pack(tmp_path, key, "0.9.0", app_id="already-here"))
    events, report = tmp_path / "events.json", tmp_path / "report.json"
    script = textwrap.dedent(
        f"""
        import json, sys
        seen = []
        def hook(event, args):
            if event.startswith("socket."):
                seen.append(event)
        sys.addaudithook(hook)
        from engine.__main__ import main
        args = ["--hub", "--import", {str(bundle)!r}, "--launch-check"]
        code = main(args + ["--report", {str(report)!r}])
        hub_events = list(seen)
        import socket
        socket.socket().close()  # control: the hook does see sockets
        result = {{"code": code, "events": hub_events, "control": "socket.__new__" in seen}}
        open({str(events)!r}, "w").write(json.dumps(result))
        """
    )
    env = {**os.environ, "QT_QPA_PLATFORM": "offscreen"}
    subprocess.run([sys.executable, "-c", script], cwd=REPO_ROOT, env=env, check=True, timeout=120)
    result = json.loads(events.read_text(encoding="utf-8"))
    assert result == {"code": 0, "events": [], "control": True}
    data = json.loads(report.read_text(encoding="utf-8"))
    assert data["status"] == "passed" and data["imported"] == [f"{APP}@1.0.0"]
    assert sorted(data["automations"]) == ["already-here", APP]
    assert not preinstalled.exists()


# --- the window ---------------------------------------------------------------------------------


@pytest.fixture
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    from engine.ui.theme import apply_theme

    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    return app


def test_hub_window_lists_imports_and_opens(qapp, store, tmp_path, key):
    from engine.ui.hub import HubWindow

    launched, asked = [], []
    window = HubWindow(
        store,
        confirm=lambda plan: asked.append(plan) or True,
        launcher=lambda *a: launched.append(a),
    )
    assert window.entries == [] and window.notice.isHidden()

    results = window.import_path(make_pack(tmp_path, key))
    assert [r.imported for r in results] == [True] and asked[0].id == APP
    assert window.notice.text().startswith("Added ") and window.notice.objectName() == "notice"
    assert [e.id for e in window.entries] == [APP]
    window.open_automation(APP)
    assert launched == [(APP, "1.0.0")]

    window.import_path(make_pack(tmp_path, key, "1.1.0"))
    window.select_version(APP, "1.0.0")
    assert store.resolve(APP) == "1.0.0"
    window.select_version(APP, "1.1.0")
    assert store.resolve(APP) == "1.1.0"

    bad = tmp_path / "bad.mmx"
    bad.write_bytes(b"nope")
    assert window.import_path(bad) is None
    assert window.notice.objectName() == "banner" and "wasn't added" in window.notice.text()
    window.copy_id()
    from PySide6.QtGui import QGuiApplication

    assert QGuiApplication.clipboard().text() == window.makemyexe_id
    window.close()


def test_import_dialog_defaults(qapp, store, tmp_path, key):
    from engine.store import ImportPlan
    from engine.ui.hub import ImportDialog

    plan = ImportPlan(APP, "1.0.0", "Word count", "job", [], 1234, ["1.1.0"])
    dialog = ImportDialog(plan)
    assert dialog.primary.text() == "Keep 1.1.0" and dialog.primary.isDefault()
    dialog.primary.click()
    assert dialog.result() == 0  # keeping the newer one says no to the import
    dialog = ImportDialog(plan)
    dialog.secondary.click()
    assert dialog.result() == 1
    update = ImportDialog(ImportPlan(APP, "1.2.0", "Word count", "job", ["x.com"], 1, ["1.1.0"]))
    assert update.primary.text() == "Add"


# --- shortcuts ----------------------------------------------------------------------------------


def test_shortcut_bytes(tmp_path):
    exe = tmp_path / "Programs" / "MakeMyEXE" / "MakeMyEXE.exe"
    data = shortcuts.link_bytes(exe, "--run word-count", "Word count (MakeMyEXE)")
    assert struct.unpack_from("<I", data)[0] == 0x4C
    assert data[4:20] == shortcuts.LINK_CLSID
    flags = struct.unpack_from("<I", data, 20)[0]
    assert flags & shortcuts.HAS_LINK_INFO and flags & shortcuts.HAS_ARGUMENTS
    link_info_size = struct.unpack_from("<I", data, 0x4C)[0]
    strings = data[0x4C + link_info_size : -4]
    texts, at = [], 0
    while at < len(strings):
        (count,) = struct.unpack_from("<H", strings, at)
        texts.append(strings[at + 2 : at + 2 + 2 * count].decode("utf-16-le"))
        at += 2 + 2 * count
    assert texts == ["Word count (MakeMyEXE)", str(exe.parent), "--run word-count", str(exe)]
    assert data.endswith(b"\0\0\0\0")
    assert str(exe).encode("utf-16-le") + b"\0\0" in data


def test_shortcut_names():
    assert shortcuts.shortcut_name('PDF: merge / "split"', "pdf") == "PDF  merge    split.lnk"
    assert shortcuts.shortcut_name("...", "pdf-merge") == "pdf-merge.lnk"


def test_shortcuts_only_for_the_installed_app(store, tmp_path, key, monkeypatch):
    store.import_bundle(make_pack(tmp_path, key))
    assert hub.add_shortcuts(store) == []  # from source: no Start menu entries
    exe = tmp_path / "Programs" / "MakeMyEXE" / "MakeMyEXE.exe"
    monkeypatch.setattr(hub, "start_menu_dir", lambda: tmp_path / "Start Menu" / "MakeMyEXE")
    monkeypatch.setattr(hub, "exe_path", lambda: exe)
    (made,) = hub.add_shortcuts(store)
    assert made.parent == tmp_path / "Start Menu" / "MakeMyEXE" and made.suffix == ".lnk"
    assert "--run word-count".encode("utf-16-le") in made.read_bytes()
    assert hub.add_shortcuts(store, ["other"]) == []


@pytest.mark.skipif(sys.platform != "win32", reason="Windows reads the shortcut back")
def test_windows_reads_our_shortcut(tmp_path):
    exe = tmp_path / "Prog ram" / "MakeMyEXE.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"MZ")
    link = shortcuts.write_shortcut(tmp_path / "Start", "Word count", "word-count", exe)
    script = (
        f"$s = (New-Object -ComObject WScript.Shell).CreateShortcut('{link}'); "
        "Write-Output $s.TargetPath; Write-Output $s.Arguments; Write-Output $s.WorkingDirectory"
    )
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command", script], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    assert out[:3] == [str(exe), "--run word-count", str(exe.parent)]
