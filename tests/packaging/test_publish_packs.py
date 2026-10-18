"""build.publish_packs: the Runner + signed catalog packs as blocks, served by the real Worker."""

import json
import shutil
import time
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from api.downloads import TOKEN_TTL_S, download_token
from build import pack as build_pack
from build import publish_catalog, publish_packs, zipblocks
from engine.pack import verify_pack
from tests.conftest import REPO_ROOT
from tests.packaging.test_publish_catalog import R2, app_folder
from tests.packaging.test_zipblocks import fake_runner, run_worker

NOW = datetime(2026, 10, 18, 12, 0, tzinfo=UTC)

needs_tools = pytest.mark.skipif(
    shutil.which("openssl") is None or shutil.which("node") is None,
    reason="needs openssl and node",
)


@pytest.fixture(scope="module")
def key(tmp_path_factory):
    private, public = build_pack.keygen("catalog-1", tmp_path_factory.mktemp("keys"))
    return private.read_text(), public


def release_dir(root: Path, version: str = "1.0.0") -> Path:
    runner = fake_runner(root / "runner-src")
    folder = root / "runner-release"
    folder.mkdir()
    with zipfile.ZipFile(folder / f"MakeMyEXE-runner-{version}.zip", "w") as z:
        for path in sorted(runner.rglob("*")):
            if path.is_file():
                z.write(path, path.relative_to(runner).as_posix())
    (folder / "release.json").write_text(json.dumps({"version": version}))
    return folder


def r2_uploader(r2: Path, done: list):
    def upload(path, key, env, content_type=None):
        target = r2.joinpath(*key.split("/"))
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        done.append(key)

    return upload


@pytest.fixture
def trusted(tmp_path, key, monkeypatch):
    path = tmp_path / "trusted_keys.json"
    path.write_text(json.dumps({"catalog-1": key[1]}))
    monkeypatch.setattr(publish_catalog, "REPO_ROOT", tmp_path / "repo")
    (tmp_path / "repo" / "build").mkdir(parents=True)
    shutil.copy2(path, tmp_path / "repo" / "build" / "trusted_keys.json")
    shutil.copytree(REPO_ROOT / "automations", tmp_path / "repo" / "automations")
    return path


@needs_tools
def test_runner_and_packs_go_up_before_the_manifest_and_the_worker_serves_them(
    tmp_path, key, trusted, monkeypatch
):
    r2, done = tmp_path / "r2", []
    monkeypatch.setattr(publish_catalog, "upload", r2_uploader(r2, done))
    artifacts = tmp_path / "artifacts"
    app_folder(artifacts)  # make-pdf, MakePDF
    result = publish_catalog.publish(
        artifacts, "abc", R2, NOW, release_dir(tmp_path), key[0], "catalog-1"
    )

    assert done[-1] == "catalog/manifest.json"  # last, as before
    assert done.index("runner/1.0.0/exe.bin") < done.index("packs/catalog/make-pdf/1.0.0/app.mmx")
    for key_name in ("runner/1.0.0/blocks.bin", "runner/1.0.0/layout.json", "runner/latest-1.json"):
        assert key_name in done
    assert "catalog/make-pdf/1.0.0/MakePDF.zip" in done  # the per-app zip stays
    pack = result["automations"]["make-pdf"]["pack"]
    assert pack["prefix"] == "packs/catalog/make-pdf/1.0.0"
    assert (pack["runner"], pack["layers"], pack["exe"]) == ("runner/1.0.0", [], "MakePDF")
    assert json.loads((r2 / "runner" / "latest-1.json").read_text())["version"] == "1.0.0"

    # The real Worker, on exactly what was uploaded: the size the manifest promises is exact.
    token = download_token(
        "secret",
        runner=pack["runner"],
        layers=[],
        pack=pack["prefix"],
        name=pack["exe"],
        now=time.time(),
    )
    import tests.packaging.test_zipblocks as zb

    monkeypatch.setattr(zb, "SECRET", "secret")
    out = tmp_path / "MakePDF.zip"
    response = run_worker(r2, token, out)
    assert response["status"] == 200
    assert int(response["headers"]["content-length"]) == pack["size_bytes"] == out.stat().st_size
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None
        assert {"MakePDF.exe", "app.mmx", "Guide.pdf"} <= set(z.namelist())
        z.extractall(tmp_path / "unzipped")
    verified = verify_pack(tmp_path / "unzipped" / "app.mmx", {"catalog-1": bytes.fromhex(key[1])})
    assert verified.manifest["kind"] == "catalog"
    assert verified.manifest["runner"]["tested_with"] == "1.0.0"
    assert TOKEN_TTL_S == 900


@needs_tools
def test_an_untrusted_key_publishes_no_packs_but_keeps_the_zips(tmp_path, key, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "build").mkdir(parents=True)
    (repo / "build" / "trusted_keys.json").write_text("{}")  # the key isn't committed yet
    monkeypatch.setattr(publish_catalog, "REPO_ROOT", repo)
    done = []
    monkeypatch.setattr(publish_catalog, "upload", r2_uploader(tmp_path / "r2", done))
    app_folder(tmp_path / "artifacts")
    result = publish_catalog.publish(
        tmp_path / "artifacts", "abc", R2, NOW, release_dir(tmp_path), key[0], "catalog-1"
    )
    assert "pack" not in result["automations"]["make-pdf"]
    assert not any(k.startswith(("runner/", "packs/")) for k in done)
    assert done[-1] == "catalog/manifest.json"


def test_without_a_key_or_runner_only_the_zips(tmp_path, monkeypatch, capsys):
    done = []
    monkeypatch.setattr(publish_catalog, "upload", r2_uploader(tmp_path / "r2", done))
    app_folder(tmp_path / "artifacts")
    publish_catalog.publish(tmp_path / "artifacts", "abc", R2, NOW, None, "", "catalog-1")
    assert "PACK_SIGNING_KEY is not set" in capsys.readouterr().out
    publish_catalog.publish(tmp_path / "artifacts", "abc", R2, NOW, None, "x", "catalog-1")
    assert "No release Runner" in capsys.readouterr().out
    assert not any(k.startswith(("runner/", "packs/")) for k in done)


def test_download_size_matches_the_worker_formula(tmp_path):
    runner = zipblocks.make_runner_blocks(fake_runner(tmp_path / "r"), tmp_path / "rb")
    source = tmp_path / "a.txt"
    source.write_bytes(b"x" * 10)
    blocks = zipblocks.make_blocks([("app.mmx", source)], tmp_path / "pb")
    entries = len(runner["entries"]) + len(blocks["entries"]) + 1
    names = sum(len(e["name"]) for e in runner["entries"] + blocks["entries"]) + 2 * len("A.exe")
    expected = (
        30 + runner["exe"]["csize"] + runner["size"] + blocks["size"] + 46 * entries + names + 22
    )
    assert publish_packs.download_size(runner, [blocks], "A.exe") == expected


def test_release_zip_with_odd_paths_is_refused(tmp_path):
    folder = tmp_path / "rel"
    folder.mkdir()
    with zipfile.ZipFile(folder / "MakeMyEXE-runner-1.0.0.zip", "w") as z:
        z.writestr("../evil.dll", b"x")
    (folder / "release.json").write_text(json.dumps({"version": "1.0.0"}))
    with pytest.raises(publish_packs.PublishError, match="unexpected path"):
        publish_packs.runner_from_release(folder, tmp_path / "work")


@needs_tools
def test_the_worker_streams_a_bundle_the_app_imports(tmp_path, key, trusted, monkeypatch):
    """Publish, stream the bundle through the real Worker, import it into the app's store, run."""
    from engine.store import AppStore

    r2, done = tmp_path / "r2", []
    monkeypatch.setattr(publish_catalog, "upload", r2_uploader(r2, done))
    artifacts = tmp_path / "artifacts"
    app_folder(artifacts)
    result = publish_catalog.publish(
        artifacts, "abc", R2, NOW, release_dir(tmp_path), key[0], "catalog-1"
    )
    pack = result["automations"]["make-pdf"]["pack"]
    assert "packs/catalog/make-pdf/1.0.0/bundle/blocks.bin" in done
    assert done.index("packs/catalog/make-pdf/1.0.0/bundle/layout.json") < len(done) - 1

    token = download_token(
        "secret", runner=None, layers=[], pack=pack["prefix"], name=pack["exe"], now=time.time()
    )
    import tests.packaging.test_zipblocks as zb

    monkeypatch.setattr(zb, "SECRET", "secret")
    out = tmp_path / "MakePDF.mmx"
    response = run_worker(r2, token, out)
    assert response["status"] == 200
    assert response["headers"]["content-disposition"] == 'attachment; filename="MakePDF.mmx"'
    assert int(response["headers"]["content-length"]) == pack["bundle_bytes"] == out.stat().st_size
    with zipfile.ZipFile(out) as z:
        assert z.testzip() is None
        assert sorted(z.namelist()) == ["bundle.json", "packs/make-pdf-1.0.0.mmx"]
        assert "MakePDF.exe" not in z.namelist()  # no Runner in a bundle
        toc = json.loads(z.read("bundle.json"))
    assert toc == {"format": 2, "packs": ["packs/make-pdf-1.0.0.mmx"], "layers": [], "licenses": []}

    store = AppStore(tmp_path / "store", {"catalog-1": bytes.fromhex(key[1])})
    (imported,) = store.import_bundle(out)
    assert imported.imported and (imported.plan.id, imported.plan.version) == ("make-pdf", "1.0.0")
    assert store.load("make-pdf").spec.id == "make-pdf"


def test_bundle_size_formula():
    layout = {"size": 1000, "entries": [{"name": "bundle.json"}, {"name": "packs/a-1.0.0.mmx"}]}
    names = len("bundle.json") + len("packs/a-1.0.0.mmx")
    assert publish_packs.bundle_size([layout]) == 1000 + 2 * 46 + names + 22
