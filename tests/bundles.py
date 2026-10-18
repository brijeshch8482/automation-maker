"""Test helpers: signed packs, layers and bundles (format 2) built like the publish jobs do."""

import hashlib
import json
import shutil
import zipfile
from pathlib import Path

from build import pack as build_pack
from tests.conftest import REPO_ROOT

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "jobs" / "word-count"
APP = "word-count"


def make_layer(root: Path, name="tinylib-1.0", value=b"VALUE = 42\n") -> tuple[Path, dict]:
    folder = root / name
    (folder / "tinylib").mkdir(parents=True)
    (folder / "tinylib" / "__init__.py").write_bytes(value)
    record = {"tinylib/__init__.py": hashlib.sha256(value).hexdigest()}
    (folder / "RECORD.json").write_bytes(json.dumps(record).encode())
    dist, version = name.rsplit("-", 1)
    digest = hashlib.sha256((folder / "RECORD.json").read_bytes()).hexdigest()
    return folder, {"dist": dist, "version": version, "record_sha256": digest}


def make_pack(
    tmp: Path, key, version="1.0.0", layers=(), tested_with="1.0.0", pem=None, app_id=APP
) -> Path:
    """The word-count job as `app_id` `version`, signed with `key` (or `pem`) as test-1."""
    app = tmp / f"app-{version}-{len(list(tmp.glob('app-*')))}"
    shutil.copytree(FIXTURE, app)
    spec = json.loads((app / "spec.json").read_text(encoding="utf-8"))
    spec["version"] = version
    spec["id"] = app_id
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
