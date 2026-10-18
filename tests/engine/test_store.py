"""The app store and bundle format 2 (engine/store.py, engine/bundle.py; DESKTOP_APP.md §4-6)."""

import hashlib
import json
import os
import shutil
import zipfile
from pathlib import Path

import pytest

from build import pack as build_pack
from engine import store as store_mod
from engine.pack import PackError
from engine.store import AppStore, StoreSettings
from tests.conftest import REPO_ROOT

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "jobs" / "word-count"
APP = "word-count"

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl CLI")


@pytest.fixture(scope="module")
def key(tmp_path_factory):
    folder = tmp_path_factory.mktemp("keys")
    private, public = build_pack.keygen("test-1", folder)
    return private.read_text(), bytes.fromhex(public)


@pytest.fixture(scope="module")
def other_key(tmp_path_factory):
    private, _ = build_pack.keygen("test-1", tmp_path_factory.mktemp("other"))
    return private.read_text()


@pytest.fixture
def store(tmp_path, key):
    return AppStore(tmp_path / "MakeMyEXE", {"test-1": key[1]})


def make_layer(root: Path, name="tinylib-1.0", value=b"VALUE = 42\n") -> tuple[Path, dict]:
    folder = root / name
    (folder / "tinylib").mkdir(parents=True)
    (folder / "tinylib" / "__init__.py").write_bytes(value)
    record = {"tinylib/__init__.py": hashlib.sha256(value).hexdigest()}
    (folder / "RECORD.json").write_bytes(json.dumps(record).encode())
    dist, version = name.rsplit("-", 1)
    digest = hashlib.sha256((folder / "RECORD.json").read_bytes()).hexdigest()
    return folder, {"dist": dist, "version": version, "record_sha256": digest}


def make_pack(tmp: Path, key, version="1.0.0", layers=(), tested_with="1.0.0", pem=None) -> Path:
    app = tmp / f"app-{version}-{len(list(tmp.glob('app-*')))}"
    shutil.copytree(FIXTURE, app)
    spec = json.loads((app / "spec.json").read_text(encoding="utf-8"))
    spec["version"] = version
    (app / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
    return build_pack.make_pack(
        app, app / "out", "job", "test-1", pem or key[0], tested_with, layers=list(layers)
    )


def make_bundle(target: Path, pack_files: list[Path], layers: list[Path] = (), **toc) -> Path:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
        names = []
        for i, pack in enumerate(pack_files):
            names.append(f"packs/app-{i}.mmx")
            z.write(pack, names[-1])
        for folder in layers:
            for path in sorted(folder.rglob("*")):
                if path.is_file():
                    z.write(path, f"layers/{folder.name}/{path.relative_to(folder).as_posix()}")
        data = {"format": 2, "packs": names, "layers": [f.name for f in layers], "licenses": []}
        z.writestr("bundle.json", json.dumps({**data, **toc}))
    return target


def rewrite_zip(source: Path, target: Path, change) -> Path:
    """Copy entry by entry; change(name, data) returns new data, None to drop, or a dict to add."""
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w") as dst:
        for info in src.infolist():
            data = change(info.filename, src.read(info))
            if isinstance(data, dict):
                for name, extra in data.items():
                    dst.writestr(name, extra)
            elif data is not None:
                dst.writestr(info.filename, data)
    return target


def store_files(store: AppStore) -> list[str]:
    root = store.root / "store"
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*")) if root.exists() else []


# --- import ------------------------------------------------------------------------------------


def test_plain_pack_imports_and_runs(store, tmp_path, key):
    results = store.import_bundle(make_pack(tmp_path, key))
    assert [(r.plan.id, r.plan.version, r.imported) for r in results] == [(APP, "1.0.0", True)]
    assert results[0].plan.network_domains == [] and results[0].plan.replaces is None
    folder = store.automations_dir / APP / "1.0.0"
    assert {"manifest.json", "manifest.sig", "spec.json", "custom_step.py"} <= {
        p.name for p in folder.iterdir()
    }
    assert store.installed() == {APP: ["1.0.0"]}
    loaded = store.load(APP)
    assert loaded.spec.id == APP and loaded.spec.version == "1.0.0"
    assert not any(p.name.startswith(".tmp-") for p in store.automations_dir.rglob("*"))


def test_bundle_with_a_layer_imports_and_reuses_it(store, tmp_path, key):
    layer_dir, pin = make_layer(tmp_path / "src")
    bundle = make_bundle(tmp_path / "b.mmx", [make_pack(tmp_path, key, layers=[pin])], [layer_dir])
    (result,) = store.import_bundle(bundle)
    assert result.imported and result.plan.new_layers == ["tinylib-1.0"]
    verified = store.open_installed(APP)
    assert verified.layer_dirs == [store.libs_dir / "tinylib-1.0"]
    assert (store.libs_dir / "tinylib-1.0" / "tinylib" / "__init__.py").read_bytes() == (
        b"VALUE = 42\n"
    )
    # A later bundle without the layer works: this PC already has it.
    lean = make_bundle(tmp_path / "lean.mmx", [make_pack(tmp_path, key, "1.1.0", layers=[pin])])
    (result,) = store.import_bundle(lean)
    assert result.imported and result.plan.new_layers == [] and result.plan.replaces == "1.0.0"
    assert store.open_installed(APP).manifest["version"] == "1.1.0"


def test_missing_layer_is_refused_and_nothing_is_written(store, tmp_path, key):
    _, pin = make_layer(tmp_path / "src")
    bundle = make_bundle(tmp_path / "b.mmx", [make_pack(tmp_path, key, layers=[pin])])
    with pytest.raises(PackError, match="incomplete"):
        store.import_bundle(bundle)
    assert store_files(store) == []


def _tampered(tmp_path, key, change_pack=None, change_layer=None, untrusted=None):
    layer_dir, pin = make_layer(tmp_path / "src")
    pack = make_pack(tmp_path, key, layers=[pin], pem=untrusted)
    bundle = make_bundle(tmp_path / "good.mmx", [pack], [layer_dir])

    def change(name, data):
        if name.startswith("packs/") and change_pack:
            inner = tmp_path / "inner.mmx"
            inner.write_bytes(data)
            return rewrite_zip(inner, tmp_path / "inner2.mmx", change_pack).read_bytes()
        if name.startswith("layers/") and change_layer:
            return change_layer(name, data)
        return data

    return rewrite_zip(bundle, tmp_path / "bad.mmx", change)


@pytest.mark.parametrize(
    "case",
    [
        "pack file changed",
        "pack file added",
        "untrusted key",
        "layer file changed",
        "layer file added",
        "layer file missing",
        "record changed",
    ],
)
def test_tampered_bundles_are_refused_before_anything_is_written(
    store, tmp_path, key, other_key, case
):
    init = "layers/tinylib-1.0/tinylib/__init__.py"
    record = "layers/tinylib-1.0/RECORD.json"
    changes = {
        "pack file changed": dict(
            change_pack=lambda n, d: d.replace(b"word", b"Word") if n == "custom_step.py" else d
        ),
        "pack file added": dict(
            change_pack=lambda n, d: {n: d, "samples/extra.txt": b"x"} if n == "spec.json" else d
        ),
        "untrusted key": dict(untrusted=other_key),
        "layer file changed": dict(change_layer=lambda n, d: b"VALUE = 666\n" if n == init else d),
        "layer file added": dict(
            change_layer=lambda n, d: {n: d, "layers/tinylib-1.0/evil.py": b"x"} if n == init else d
        ),
        "layer file missing": dict(change_layer=lambda n, d: None if n == init else d),
        "record changed": dict(change_layer=lambda n, d: d + b" " if n == record else d),
    }
    bad = _tampered(tmp_path, key, **changes[case])
    with pytest.raises(PackError, match="was changed"):
        store.import_bundle(bad)
    assert store_files(store) == []


def test_layer_paths_must_stay_inside_the_layer(store, tmp_path, key):
    folder = tmp_path / "src" / "tinylib-1.0"
    folder.mkdir(parents=True)
    record = json.dumps({"../evil.py": hashlib.sha256(b"x").hexdigest()}).encode()
    (folder / "RECORD.json").write_bytes(record)
    pin = {"dist": "tinylib", "version": "1.0", "record_sha256": hashlib.sha256(record).hexdigest()}
    bundle = make_bundle(tmp_path / "b.mmx", [make_pack(tmp_path, key, layers=[pin])], [folder])
    with zipfile.ZipFile(bundle, "a") as z:
        z.writestr("layers/tinylib-1.0/../evil.py", b"x")
    with pytest.raises(PackError, match="was changed"):
        store.import_bundle(bundle)
    assert store_files(store) == [] and not (store.root / "store" / "evil.py").exists()


@pytest.mark.parametrize(
    ("toc", "message"),
    [
        ({"format": 3}, "newer MakeMyEXE"),
        ({"format": "2"}, "was changed"),
        ({"packs": ["packs/missing.mmx"]}, "was changed"),
        ({"packs": "packs/app-0.mmx"}, "was changed"),
        ({"packs": []}, "was changed"),
        ({"licenses": ["../x.json"]}, "was changed"),
    ],
)
def test_bad_table_of_contents(store, tmp_path, key, toc, message):
    bundle = make_bundle(tmp_path / "b.mmx", [make_pack(tmp_path, key)], **toc)
    with pytest.raises(PackError, match=message):
        store.import_bundle(bundle)
    assert store_files(store) == []


def test_not_a_bundle(store, tmp_path):
    (tmp_path / "x.mmx").write_bytes(b"not a zip")
    with pytest.raises(PackError, match="was changed"):
        store.import_bundle(tmp_path / "x.mmx")
    with pytest.raises(PackError, match="incomplete"):
        store.import_bundle(tmp_path / "missing.mmx")


def test_app_too_old(store, tmp_path, key):
    pack = make_pack(tmp_path, key, tested_with="1.4.0")
    with pytest.raises(PackError, match=r"Update MakeMyEXE to 1\.4\.0 or newer"):
        store.import_bundle(pack)
    newer = AppStore(store.root, store.trusted_keys, app_version="1.4.2")
    assert newer.import_bundle(pack)[0].imported


def test_a_failed_write_leaves_the_store_as_it_was(store, tmp_path, key, monkeypatch):
    store.import_bundle(make_pack(tmp_path, key, "1.0.0"))
    before = store_files(store)
    real_rename = os.rename

    def failing(src, dst):
        if Path(dst).name == "1.1.0":
            raise OSError("disk full")
        real_rename(src, dst)

    monkeypatch.setattr(store_mod.os, "rename", failing)
    with pytest.raises(OSError):
        store.import_bundle(make_pack(tmp_path, key, "1.1.0"))
    assert store_files(store) == before
    assert store.installed() == {APP: ["1.0.0"]}


def test_reinstall_replaces_a_damaged_copy(store, tmp_path, key):
    pack = make_pack(tmp_path, key)
    store.import_bundle(pack)
    (store.automations_dir / APP / "1.0.0" / "spec.json").write_text("{}", encoding="utf-8")
    with pytest.raises(PackError, match="was changed"):
        store.open_installed(APP)
    (result,) = store.import_bundle(pack)
    assert result.plan.reinstall and result.imported
    store.open_installed(APP)


# --- versions -----------------------------------------------------------------------------------


def test_downgrade_keeps_the_newer_version_unless_confirmed(store, tmp_path, key):
    store.import_bundle(make_pack(tmp_path, key, "1.1.0"))
    old = make_pack(tmp_path, key, "1.0.0")
    (result,) = store.import_bundle(old)
    assert result.plan.downgrade and not result.imported
    assert store.installed() == {APP: ["1.1.0"]}

    asked = []
    (result,) = store.import_bundle(old, confirm=lambda plan: asked.append(plan) or True)
    assert result.imported and asked[0].replaces == "1.1.0"
    assert store.installed() == {APP: ["1.1.0", "1.0.0"]}
    assert store.resolve(APP) == "1.0.0"  # the user chose it
    store.select(APP, None)
    assert store.resolve(APP) == "1.1.0"
    assert store.resolve(APP, "1.0.0") == "1.0.0"
    with pytest.raises(PackError, match="isn't installed"):
        store.resolve(APP, "0.9.0")


def test_only_the_last_two_versions_are_kept_and_unused_layers_go(store, tmp_path, key):
    src = tmp_path / "src"
    one, pin1 = make_layer(src, "tinylib-1.0")
    two, pin2 = make_layer(src, "tinylib-2.0", b"VALUE = 2\n")
    store.import_bundle(
        make_bundle(tmp_path / "a.mmx", [make_pack(tmp_path, key, "1.0.0", [pin1])], [one])
    )
    store.import_bundle(
        make_bundle(tmp_path / "b.mmx", [make_pack(tmp_path, key, "1.1.0", [pin2])], [two])
    )
    store.import_bundle(make_pack(tmp_path, key, "1.2.0"))
    assert store.installed() == {APP: ["1.2.0", "1.1.0"]}
    assert not (store.automations_dir / APP / "1.0.0").exists()
    (store.libs_dir / ".tmp-leftover").mkdir()

    removed = store.collect_garbage()
    assert sorted(removed) == ["store/libs/.tmp-leftover", "store/libs/tinylib-1.0"]
    assert (store.libs_dir / "tinylib-2.0").is_dir()
    store.open_installed(APP, "1.1.0")


def test_garbage_collection_drops_unlisted_versions(store, tmp_path, key):
    store.import_bundle(make_pack(tmp_path, key))
    stray = store.automations_dir / APP / "9.9.9"
    shutil.copytree(store.automations_dir / APP / "1.0.0", stray)
    unknown = store.automations_dir / "someone-else"
    unknown.mkdir()
    assert sorted(store.collect_garbage()) == [
        "store/automations/someone-else",
        "store/automations/word-count/9.9.9",
    ]
    store.open_installed(APP)


def test_keep_versions_is_a_setting(tmp_path, key):
    store = AppStore(tmp_path / "s", {"test-1": key[1]}, StoreSettings(keep_versions=1))
    store.import_bundle(make_pack(tmp_path, key, "1.0.0"))
    store.import_bundle(make_pack(tmp_path, key, "1.1.0"))
    assert store.installed() == {APP: ["1.1.0"]}


# --- run: verified again every time ---------------------------------------------------------


def test_every_run_verifies_the_installed_copy(store, tmp_path, key):
    layer_dir, pin = make_layer(tmp_path / "src")
    store.import_bundle(
        make_bundle(tmp_path / "b.mmx", [make_pack(tmp_path, key, layers=[pin])], [layer_dir])
    )
    folder = store.automations_dir / APP / "1.0.0"
    init = store.libs_dir / "tinylib-1.0" / "tinylib" / "__init__.py"

    def refused(match="was changed"):
        with pytest.raises(PackError, match=match):
            store.open_installed(APP)

    step = folder / "custom_step.py"
    original = step.read_bytes()
    step.write_bytes(original + b"\nimport socket\n")
    refused()
    step.write_bytes(original)
    (folder / "samples").mkdir(exist_ok=True)
    (folder / "samples" / "extra.txt").write_bytes(b"x")
    refused()
    (folder / "samples" / "extra.txt").unlink()
    init.write_bytes(b"VALUE = 666\n")
    refused()
    init.write_bytes(b"VALUE = 42\n")
    (init.parent / "evil.py").write_bytes(b"")
    refused()
    (init.parent / "evil.py").unlink()
    store.open_installed(APP)
    shutil.rmtree(store.libs_dir / "tinylib-1.0")
    refused("incomplete")


def test_a_signed_pack_moved_into_another_version_is_refused(store, tmp_path, key):
    store.import_bundle(make_pack(tmp_path, key, "1.0.0"))
    store.import_bundle(make_pack(tmp_path, key, "1.1.0"))
    old, new = store.automations_dir / APP / "1.0.0", store.automations_dir / APP / "1.1.0"
    shutil.rmtree(new)
    shutil.copytree(old, new)  # "1.1.0" now holds the signed 1.0.0
    with pytest.raises(PackError, match="was changed"):
        store.open_installed(APP, "1.1.0")


def test_a_newer_app_runs_it_an_older_one_refuses(store, tmp_path, key):
    store.import_bundle(make_pack(tmp_path, key))
    older = AppStore(store.root, store.trusted_keys, app_version="0.9.0")
    with pytest.raises(PackError, match="Update MakeMyEXE"):
        older.open_installed(APP)


def test_not_installed(store):
    with pytest.raises(PackError, match="isn't installed"):
        store.open_installed(APP)


# --- index, install id, licenses ----------------------------------------------------------------


def test_broken_index_is_rebuilt_from_the_store(store, tmp_path, key):
    store.import_bundle(make_pack(tmp_path, key, "1.0.0"))
    store.import_bundle(make_pack(tmp_path, key, "1.1.0"))
    store.index_path.write_text("{not json", encoding="utf-8")
    assert store.installed() == {APP: ["1.1.0", "1.0.0"]}
    store.open_installed(APP)


def test_install_id_is_made_once(store):
    first = store.install_id()
    assert len(bytes.fromhex(first)) == 16
    assert store.install_id() == first
    data = json.loads((store.root / "install.json").read_text(encoding="utf-8"))
    assert data["format"] == 1 and data["install_id"] == first


def test_license_slot(tmp_path, key):
    pack = make_pack(tmp_path, key)
    bundle = make_bundle(tmp_path / "b.mmx", [pack], licenses=["licenses/lic_1.json"])
    with zipfile.ZipFile(bundle, "a") as z:
        z.writestr("licenses/lic_1.json", b"{}")
        z.writestr("licenses/lic_1.sig", b"\0" * 64)
    free = AppStore(tmp_path / "free", {"test-1": key[1]})
    assert free.import_bundle(bundle)[0].imported  # no kind needs a license yet (§15)
    licensed = AppStore(
        tmp_path / "paid", {"test-1": key[1]}, StoreSettings(licensed_kinds=frozenset({"job"}))
    )
    with pytest.raises(PackError, match="licensed to another MakeMyEXE ID"):
        licensed.import_bundle(bundle)
    with zipfile.ZipFile(bundle) as z:
        assert "licenses/lic_1.sig" in z.namelist()
    missing_sig = make_bundle(tmp_path / "c.mmx", [pack], licenses=["licenses/lic_2.json"])
    with pytest.raises(PackError, match="was changed"):
        free.import_bundle(missing_sig)


def test_store_location(monkeypatch, tmp_path):
    monkeypatch.setenv("MAKEMYEXE_STORE_DIR", str(tmp_path / "custom"))
    assert store_mod.default_root() == tmp_path / "custom"
    monkeypatch.delenv("MAKEMYEXE_STORE_DIR")
    monkeypatch.setattr(store_mod.sys, "platform", "win32")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "Local"))
    assert store_mod.default_root() == tmp_path / "Local" / "MakeMyEXE"


def test_app_version_is_the_engine_version():
    import tomllib

    from engine import __version__

    project = tomllib.loads((REPO_ROOT / "engine" / "pyproject.toml").read_text(encoding="utf-8"))
    assert project["project"]["version"] == __version__
