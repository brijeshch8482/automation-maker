"""Signed app packs: Ed25519, making (build/pack.py) and verifying (engine/pack.py) them."""

import hashlib
import json
import os
import shutil
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from build import pack as build_pack
from engine import __main__ as cli
from engine import ed25519, keys, pack
from engine.pack import PackError, load_pack, started_from_zip, verify_pack
from engine.smoke import smoke_test
from spec.fingerprint import spec_sha256
from tests.conftest import AUTOMATIONS_DIR, REPO_ROOT

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "jobs" / "word-count"
NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)

pytestmark = pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl CLI")


@pytest.fixture(scope="module")
def key(tmp_path_factory):
    folder = tmp_path_factory.mktemp("keys")
    private, public = build_pack.keygen("test-1", folder)
    return private.read_text(), bytes.fromhex(public)


@pytest.fixture
def trusted(key):
    return {"test-1": key[1]}


def make(app_dir: Path, out: Path, key, kind="job", **kwargs) -> Path:
    return build_pack.make_pack(app_dir, out, kind, "test-1", key[0], "1.0.0", **kwargs)


def rewrite(source: Path, target: Path, change) -> Path:
    """Copy a pack entry by entry; `change(name, data)` returns new data or None to drop it."""
    with zipfile.ZipFile(source) as src, zipfile.ZipFile(target, "w") as dst:
        for info in src.infolist():
            data = change(info.filename, src.read(info))
            if data is not None:
                dst.writestr(info.filename, data)
    return target


def resign(source: Path, target: Path, key, edit) -> Path:
    """A pack whose manifest was edited and then properly signed again (a valid signature)."""
    with zipfile.ZipFile(source) as src:
        manifest = json.loads(src.read("manifest.json"))
        files = {n: src.read(n) for n in src.namelist() if not n.startswith("manifest.")}
    edit(manifest, files)
    data = json.dumps(manifest).encode()
    return build_pack.write_pack(target, data, build_pack.openssl_sign(key[0], data), files)


# --- Ed25519 ------------------------------------------------------------------------------

RFC8032 = [
    (
        "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a",
        "",
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e065224901555fb8821590a33bac"
        "c61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b",
    ),
    (
        "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c",
        "72",
        "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da085ac1e43e15996e"
        "458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00",
    ),
    (
        "fc51cd8e6218a1a38da47ed00230f0580816ed13ba3303ac5deb911548908025",
        "af82",
        "6291d657deec24024827e69c3abe01a30ce548a284743a445e3680d7db5ac3ac18ff9b538d16f290"
        "ae67f760984dc6594a7c15e9716ed28dc027beceea1ec40a",
    ),
]


@pytest.mark.parametrize(("public", "message", "signature"), RFC8032)
def test_ed25519_rfc8032_vectors(public, message, signature):
    pk, msg, sig = bytes.fromhex(public), bytes.fromhex(message), bytes.fromhex(signature)
    assert ed25519.verify(pk, msg, sig)
    assert not ed25519.verify(pk, msg + b"x", sig)
    assert not ed25519.verify(pk, msg, sig[:63] + bytes([sig[63] ^ 1]))
    # S >= L (malleable form) and wrong lengths are refused.
    s = int.from_bytes(sig[32:], "little") + ed25519.L
    assert not ed25519.verify(pk, msg, sig[:32] + s.to_bytes(32, "little"))
    assert not ed25519.verify(pk[:31], msg, sig)
    assert not ed25519.verify(pk, msg, sig[:63])


def test_ed25519_verifies_openssl_signatures(key):
    signature = build_pack.openssl_sign(key[0], b"manifest bytes")
    assert ed25519.verify(key[1], b"manifest bytes", signature)
    assert not ed25519.verify(key[1], b"manifest bytez", signature)


# --- Making packs ---------------------------------------------------------------------------


def test_pack_holds_exactly_the_app_files(tmp_path, key):
    path = make(FIXTURE, tmp_path, key)
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
    assert names == [
        "manifest.json",
        "manifest.sig",
        "custom_step.py",
        "samples/Notes.txt",
        "spec.json",
    ]  # never the tests
    assert (
        manifest["files"]["spec.json"]
        == hashlib.sha256((FIXTURE / "spec.json").read_bytes()).hexdigest()
    )
    assert (manifest["id"], manifest["version"], manifest["kind"]) == ("word-count", "1.0.0", "job")
    assert manifest["runner"] == {"major": 1, "tested_with": "1.0.0"}
    assert manifest["network"] == {"required": False, "domains": []}
    assert manifest["key_id"] == "test-1"
    assert manifest["layers"] == []


def test_same_files_same_manifest():
    files = build_pack.collect(FIXTURE)
    a = build_pack.make_manifest(files, "job", "test-1", "1.0.0", now=NOW)
    b = build_pack.make_manifest(build_pack.collect(FIXTURE), "job", "test-1", "1.0.0", now=NOW)
    assert a == b


def test_pack_refuses_an_unconfirmed_spec(tmp_path, key):
    confirmed = spec_sha256(json.loads((FIXTURE / "spec.json").read_text(encoding="utf-8")))
    make(FIXTURE, tmp_path / "ok", key, expect_spec_sha256=confirmed)
    with pytest.raises(build_pack.PackError, match="not the spec the user confirmed"):
        make(FIXTURE, tmp_path / "bad", key, expect_spec_sha256="0" * 64)


def test_collect_refuses_links_and_odd_files(tmp_path):
    app = tmp_path / "app"
    shutil.copytree(FIXTURE, app)
    (app / "assets").mkdir()
    if os.name != "nt":  # Windows can't even name such a file
        (app / "assets" / "logo|1.png").write_bytes(b"x")
        with pytest.raises(build_pack.PackError, match="may not be in a pack"):
            build_pack.collect(app)
        (app / "assets" / "logo|1.png").unlink()
    (app / "test_custom_step.py").write_text("x")
    assert "test_custom_step.py" not in build_pack.collect(app)  # tests never ship
    if os.name == "nt":
        return  # links need extra rights on Windows
    (app / "spec.json").rename(app / "real.json")
    (app / "spec.json").symlink_to(app / "real.json")
    with pytest.raises(build_pack.PackError, match="is a link"):
        build_pack.collect(app)


def test_build_and_engine_agree_on_names_and_fingerprints():
    assert build_pack.ALLOWED_FILE.pattern == pack.ALLOWED_FILE.pattern
    assert build_pack.RUNNER_MAJOR == pack.RUNNER_MAJOR
    spec = json.loads((AUTOMATIONS_DIR / "invoice-generator" / "spec.json").read_text("utf-8"))
    assert build_pack.spec_sha256(spec) == spec_sha256(spec)


def test_keygen_writes_a_private_key_only_the_owner_can_read(tmp_path):
    private, public = build_pack.keygen("other-1", tmp_path)
    assert len(bytes.fromhex(public)) == 32
    if os.name != "nt":
        assert private.stat().st_mode & 0o077 == 0
    with pytest.raises(build_pack.PackError, match="already exists"):
        build_pack.keygen("other-1", tmp_path)


# --- Verifying packs -------------------------------------------------------------------------


def test_a_signed_pack_runs(tmp_path, key, trusted):
    path = make(FIXTURE, tmp_path, key)
    loaded = load_pack(path, trusted)
    assert loaded.spec.id == "word-count"
    assert (loaded.dir / "custom_step.py").is_file()
    assert smoke_test(loaded)["status"] == "passed"


@pytest.mark.parametrize("app", sorted(p.name for p in AUTOMATIONS_DIR.iterdir() if p.is_dir()))
def test_every_catalog_app_runs_from_its_pack(tmp_path, key, trusted, app):
    path = make(AUTOMATIONS_DIR / app, tmp_path, key, kind="catalog")
    assert smoke_test(load_pack(path, trusted))["status"] == "passed"


@pytest.mark.parametrize(
    "change",
    [
        lambda n, d: d + b" " if n == "custom_step.py" else d,  # code changed
        lambda n, d: None if n == "samples/Notes.txt" else d,  # file removed
        lambda n, d: d.replace(b'"job"', b'"catalog"') if n == "manifest.json" else d,
        lambda n, d: b"\0" * 64 if n == "manifest.sig" else d,
        lambda n, d: None if n == "manifest.sig" else d,
    ],
    ids=["changed-code", "missing-file", "edited-manifest", "bad-signature", "no-signature"],
)
def test_changed_packs_are_refused(tmp_path, key, trusted, change):
    bad = rewrite(make(FIXTURE, tmp_path, key), tmp_path / "bad.mmx", change)
    with pytest.raises(PackError, match="was changed after MakeMyEXE made it"):
        verify_pack(bad, trusted)


def test_an_added_file_is_refused(tmp_path, key, trusted):
    good = make(FIXTURE, tmp_path, key)
    bad = tmp_path / "bad.mmx"
    shutil.copy2(good, bad)
    with zipfile.ZipFile(bad, "a") as archive:
        archive.writestr("custom_step2.py", "print('hi')")
    with pytest.raises(PackError, match="was changed"):
        verify_pack(bad, trusted)


def test_only_trusted_keys(tmp_path, key, tmp_path_factory):
    path = make(FIXTURE, tmp_path, key)
    other = build_pack.keygen("test-1", tmp_path_factory.mktemp("other"))[1]
    for trusted in ({}, {"test-1": bytes.fromhex(other)}, {"test-2": key[1]}):
        with pytest.raises(PackError, match="was changed"):
            verify_pack(path, trusted)


@pytest.mark.parametrize(
    ("edit", "message"),
    [
        (lambda m, f: m["runner"].update(major=2), "different version of MakeMyEXE"),
        (lambda m, f: m.update(id="other-app"), "was changed"),
        (lambda m, f: m.update(kind="unknown"), "was changed"),
        (lambda m, f: m["files"].update({"../evil.py": "0" * 64}), "was changed"),
    ],
    ids=["runner-major", "id-mismatch", "kind", "path"],
)
def test_signed_but_wrong_manifests_are_refused(tmp_path, key, trusted, edit, message):
    bad = resign(make(FIXTURE, tmp_path, key), tmp_path / "bad.mmx", key, edit)
    with pytest.raises(PackError, match=message):
        verify_pack(bad, trusted)


def test_missing_or_broken_pack(tmp_path, trusted):
    with pytest.raises(PackError, match="incomplete"):
        verify_pack(tmp_path / "app.mmx", trusted)
    (tmp_path / "app.mmx").write_bytes(b"not a zip")
    with pytest.raises(PackError, match="was changed"):
        verify_pack(tmp_path / "app.mmx", trusted)


# --- Layers -----------------------------------------------------------------------------------


def make_layer(app_dir: Path) -> dict:
    folder = app_dir / "libs" / "tinylib-1.0"
    (folder / "tinylib").mkdir(parents=True)
    (folder / "tinylib" / "__init__.py").write_bytes(b"VALUE = 42\n")
    record = {"tinylib/__init__.py": hashlib.sha256(b"VALUE = 42\n").hexdigest()}
    (folder / "RECORD.json").write_bytes(json.dumps(record).encode())
    digest = hashlib.sha256((folder / "RECORD.json").read_bytes()).hexdigest()
    return {"dist": "tinylib", "version": "1.0", "record_sha256": digest}


def test_layers_are_verified_file_by_file(tmp_path, key, trusted):
    layer = make_layer(tmp_path)
    path = resign(make(FIXTURE, tmp_path / "p", key), tmp_path / "app.mmx", key,
                  lambda m, f: m.update(layers=[layer]))  # fmt: skip
    verified = verify_pack(path, trusted, tmp_path)
    assert verified.layer_dirs == [tmp_path / "libs" / "tinylib-1.0"]

    init = tmp_path / "libs" / "tinylib-1.0" / "tinylib" / "__init__.py"
    init.write_bytes(b"VALUE = 666\n")
    with pytest.raises(PackError, match="was changed"):
        verify_pack(path, trusted, tmp_path)
    init.write_bytes(b"VALUE = 42\n")
    (init.parent / "extra.py").write_bytes(b"")
    with pytest.raises(PackError, match="was changed"):
        verify_pack(path, trusted, tmp_path)
    shutil.rmtree(tmp_path / "libs")
    with pytest.raises(PackError, match="incomplete"):
        verify_pack(path, trusted, tmp_path)


# --- Runner start-up ------------------------------------------------------------------------


def test_runner_accepts_only_packs(monkeypatch, tmp_path):
    monkeypatch.setattr(cli, "is_runner", lambda: True)
    monkeypatch.setattr(cli.sys, "executable", str(tmp_path / "App" / "MakeMyEXE.exe"))
    with pytest.raises(PackError, match="only signed"):
        cli._load(AUTOMATIONS_DIR / "invoice-generator" / "spec.json")
    monkeypatch.setattr(cli.sys, "executable", str(tmp_path / "Temp1_App.zip" / "App.exe"))
    with pytest.raises(PackError, match="Extract the zip first"):
        cli._load(tmp_path / "app.mmx")


def test_installed_runner_without_arguments_opens_the_hub(monkeypatch, tmp_path):
    # The Start menu shortcut starts MakeMyEXE.exe with no arguments and no app.mmx beside it.
    monkeypatch.setattr(cli, "is_runner", lambda: True)
    monkeypatch.setattr(cli.sys, "executable", str(tmp_path / "MakeMyEXE" / "MakeMyEXE.exe"))
    opened = []
    monkeypatch.setattr(cli, "_hub", lambda args: opened.append(args) or 0)
    assert cli.main([]) == 0
    assert len(opened) == 1 and opened[0].hub and opened[0].spec is None


def test_started_from_zip():
    assert started_from_zip(
        Path("C:/Users/a/AppData/Local/Temp/Temp1_MakePDF.zip/MakePDF/MakePDF.exe")
    )
    assert not started_from_zip(Path("C:/Users/a/Downloads/MakePDF/MakePDF.exe"))


def test_cli_runs_a_pack_with_dev_keys(tmp_path, key, monkeypatch, capsys):
    path = make(FIXTURE, tmp_path, key)
    keys_file = tmp_path / "keys.json"
    keys_file.write_text(json.dumps({"test-1": key[1].hex()}))
    monkeypatch.setenv("MAKEMYEXE_TRUSTED_KEYS", str(keys_file))
    monkeypatch.setenv("MAKEMYEXE_DATA_DIR", str(tmp_path / "data"))
    try:
        assert cli.main([str(path), "--smoke-test"]) == 0
    finally:
        from engine.guards import unblock_network

        unblock_network()
    assert json.loads(capsys.readouterr().out)["status"] == "passed"


def test_trusted_keys_file():
    assert keys.parse_keys('{"_comment": "x", "a-1": "' + "11" * 32 + '"}') == {"a-1": b"\x11" * 32}
    with pytest.raises(ValueError, match="32-byte"):
        keys.parse_keys('{"a-1": "abcd"}')
    # The committed file parses (it may hold no keys until they are made: DEPLOY.md §9).
    keys.parse_keys(keys.REPO_FILE.read_text(encoding="utf-8"))
