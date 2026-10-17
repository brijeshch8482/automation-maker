"""build.zipblocks + the download Worker (worker/): pre-built blocks merged into one valid zip."""

import hashlib
import json
import shutil
import subprocess
import time
import zipfile
from pathlib import Path

import pytest

from api.downloads import TOKEN_TTL_S, download_token
from build import pack as build_pack
from build import zipblocks
from engine.pack import verify_pack
from tests.conftest import REPO_ROOT

WORKER = REPO_ROOT / "worker"
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "jobs" / "word-count"
SECRET = "test-download-secret"

needs_tools = pytest.mark.skipif(
    shutil.which("node") is None or shutil.which("openssl") is None,
    reason="needs node and openssl",
)


def token(payload: dict, secret: str = SECRET) -> str:
    """A token made exactly as the API makes it (api.downloads), checked by the Worker's JS."""
    now = payload["exp"] - TOKEN_TTL_S
    fields = {k: payload[k] for k in ("runner", "layers", "pack", "name")}
    return download_token(secret, **fields, now=now)


def run_worker(r2: Path, tok: str, out: Path) -> dict:
    result = subprocess.run(
        ["node", str(WORKER / "test" / "harness.mjs"), str(r2), SECRET, tok, str(out)],
        capture_output=True,
        text=True,
        check=True,
        timeout=60,
    )
    return json.loads(result.stdout)


def fake_runner(folder: Path) -> Path:
    (folder / "_internal" / "PySide6").mkdir(parents=True)
    (folder / zipblocks.EXE_NAME).write_bytes(b"MZ" + bytes(range(256)) * 300)
    (folder / "_internal" / "python312.dll").write_bytes(b"dll" * 5000)
    (folder / "_internal" / "PySide6" / "Qt6Core.dll").write_bytes(bytes(range(256)) * 900)
    (folder / "_internal" / "trusted_keys.json").write_text("{}")
    return folder


def make_layer(root: Path) -> tuple[Path, dict]:
    folder = root / "libs" / "tinylib-1.0"
    (folder / "tinylib").mkdir(parents=True)
    (folder / "tinylib" / "__init__.py").write_bytes(b"VALUE = 42\n")
    record = {"tinylib/__init__.py": hashlib.sha256(b"VALUE = 42\n").hexdigest()}
    (folder / "RECORD.json").write_bytes(json.dumps(record).encode())
    digest = hashlib.sha256((folder / "RECORD.json").read_bytes()).hexdigest()
    return folder, {"dist": "tinylib", "version": "1.0", "record_sha256": digest}


def test_blocks_are_the_local_part_of_a_zip(tmp_path):
    source = tmp_path / "a.txt"
    source.write_bytes(b"hello " * 100)
    layout = zipblocks.make_blocks([("docs/a.txt", source)], tmp_path / "out")
    data = (tmp_path / "out" / "blocks.bin").read_bytes()
    assert len(data) == layout["size"]
    (entry,) = layout["entries"]
    assert data[entry["offset"] : entry["offset"] + 4] == b"PK\x03\x04"
    assert (entry["usize"], entry["name"]) == (600, "docs/a.txt")
    with pytest.raises(zipblocks.BlockError, match="bad entry name"):
        zipblocks.make_blocks([("../x", source)], tmp_path / "bad")


def test_runner_blocks_keep_the_exe_apart(tmp_path):
    runner = fake_runner(tmp_path / "runner")
    layout = zipblocks.make_runner_blocks(runner, tmp_path / "out")
    assert zipblocks.EXE_NAME not in {e["name"] for e in layout["entries"]}
    assert (tmp_path / "out" / "exe.bin").stat().st_size == layout["exe"]["csize"]
    with pytest.raises(zipblocks.BlockError, match="missing"):
        zipblocks.make_runner_blocks(tmp_path / "out", tmp_path / "nope")


@needs_tools
def test_worker_merges_runner_layer_and_pack_into_one_valid_zip(tmp_path):
    keys = tmp_path / "keys"
    private, public = build_pack.keygen("test-1", keys)
    r2 = tmp_path / "r2"

    runner = fake_runner(tmp_path / "runner")
    zipblocks.make_runner_blocks(runner, r2 / "runner" / "1.0.0")

    layer_dir, layer = make_layer(tmp_path / "layer-src")
    files = [(f"libs/tinylib-1.0/{p.relative_to(layer_dir).as_posix()}", p)
             for p in sorted(layer_dir.rglob("*")) if p.is_file()]  # fmt: skip
    zipblocks.make_blocks(files, r2 / "layers" / "tinylib" / "1.0")

    pack = build_pack.make_pack(
        FIXTURE, tmp_path / "pack", "job", "test-1", private.read_text(), "1.0.0", layers=[layer]
    )
    guide = tmp_path / "Guide.pdf"
    guide.write_bytes(b"%PDF-1.4 fake guide")
    pack_prefix = "packs/jobs/job_01ABCDEFGHJKMNPQRSTVWXYZ00/attempt-0"
    zipblocks.make_blocks([("app.mmx", pack), ("Guide.pdf", guide)], r2 / pack_prefix)

    payload = {
        "runner": "runner/1.0.0",
        "layers": ["layers/tinylib/1.0"],
        "pack": pack_prefix,
        "name": "WordCount",
        "exp": int(time.time()) + 900,
    }
    out = tmp_path / "WordCount.zip"
    response = run_worker(r2, token(payload), out)

    assert response["status"] == 200
    assert response["headers"]["content-type"] == "application/zip"
    assert response["headers"]["content-disposition"] == 'attachment; filename="WordCount.zip"'
    assert int(response["headers"]["content-length"]) == out.stat().st_size == response["bytes"]
    with zipfile.ZipFile(out) as archive:
        assert archive.testzip() is None  # every CRC checks out
        assert sorted(archive.namelist()) == [
            "Guide.pdf",
            "WordCount.exe",  # the Runner's exe, renamed for this app
            "_internal/PySide6/Qt6Core.dll",
            "_internal/python312.dll",
            "_internal/trusted_keys.json",
            "app.mmx",
            "libs/tinylib-1.0/RECORD.json",
            "libs/tinylib-1.0/tinylib/__init__.py",
        ]
        assert archive.read("WordCount.exe") == (runner / zipblocks.EXE_NAME).read_bytes()
        archive.extractall(tmp_path / "extracted")
    # What the user unzips is exactly what the Runner verifies: signature, files and layer.
    verified = verify_pack(tmp_path / "extracted" / "app.mmx", {"test-1": bytes.fromhex(public)})
    assert verified.layer_dirs == [tmp_path / "extracted" / "libs" / "tinylib-1.0"]


@needs_tools
def test_worker_refuses_forged_or_expired_tokens(tmp_path):
    payload = {"runner": "runner/1.0.0", "layers": [], "pack": "packs/catalog/a/1.0.0",
               "name": "A", "exp": int(time.time()) + 900}  # fmt: skip
    forged = token(payload, secret="not-the-secret")
    assert run_worker(tmp_path, forged, tmp_path / "x.zip")["status"] == 403
    expired = token({**payload, "exp": 1})
    assert run_worker(tmp_path, expired, tmp_path / "x.zip")["status"] == 410
