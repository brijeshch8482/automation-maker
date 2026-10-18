"""Publish the Runner and signed catalog packs as zip blocks (Phase 2b, ARCHITECTURE.md §8.6).

Called by build/publish_catalog.py in CI's "publish catalog" job (push to main, environment
`catalog`), after the per-app zips and before catalog/manifest.json. Standard library only.

- The Runner: the release copy from the `runner (Windows)` job (`build.runner --release-out`:
  committed keys only), as `runner/<version>/{exe.bin, blocks.bin, layout.json}` plus the
  pointer `runner/latest-<major>.json`.
- Each catalog app: a pack made and signed here from automations/<id>/ in the checked-out
  commit (data, never a build artifact), with PACK_SIGNING_KEY, as
  `packs/catalog/<id>/<version>/{app.mmx, Guide.pdf, blocks.bin, layout.json}`.
- The manifest entry gets `pack: {prefix, runner, layers, exe, size_bytes}`; the API then serves
  that app through the download Worker (api/downloads.py).

Nothing is published if the signing key's public half isn't in build/trusted_keys.json: a
Runner that doesn't trust the key would refuse every pack. The log then prints the public key
to add (it is public).
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import zipfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from build import pack as build_pack
from build import zipblocks
from build.publish import PublishError

RUNNER_MAJOR = build_pack.RUNNER_MAJOR
# upload(path, key, content_type)
Uploader = Callable[[Path, str, str], None]


class KeyNotTrusted(PublishError):
    """Setup isn't finished (docs/DEPLOY.md §9): skip the packs, keep the per-app zips."""


def public_key_hex(private_key_pem: str) -> str:
    result = subprocess.run(
        ["openssl", "pkey", "-pubout", "-outform", "DER"],
        input=private_key_pem.encode(),
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or len(result.stdout) < 32:
        raise PublishError("PACK_SIGNING_KEY is not an Ed25519 private key")
    return result.stdout[-32:].hex()


def trusted_keys(path: Path) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v.lower() for k, v in data.items() if not k.startswith("_")}


def download_size(runner: dict[str, Any], blocks: list[dict[str, Any]], exe_name: str) -> int:
    """Exactly what the Worker sends (worker/src/zip.js planZip): headers, blocks, directory."""
    name = exe_name.encode()
    total = 30 + len(name) + runner["exe"]["csize"] + 46 + len(name)
    for layout in [runner, *blocks]:
        total += layout["size"]
        total += sum(46 + len(e["name"].encode()) for e in layout["entries"])
    return total + 22


def runner_from_release(release_dir: Path, work: Path) -> tuple[str, Path]:
    """The release Runner folder and its version, from the runner-release artifact."""
    info = json.loads((release_dir / "release.json").read_text(encoding="utf-8"))
    version = str(info["version"])
    (archive,) = release_dir.glob("*.zip")
    folder = work / "runner"
    with zipfile.ZipFile(archive) as z:
        for member in z.namelist():  # our own build; still refuse odd paths
            if member.startswith("/") or ".." in member.split("/"):
                raise PublishError(f"unexpected path in the Runner zip: {member}")
        z.extractall(folder)
    return version, folder


def publish_packs(
    apps: list[dict[str, Any]],
    automations_dir: Path,
    release_dir: Path,
    private_key_pem: str,
    key_id: str,
    trusted_file: Path,
    upload: Uploader,
) -> dict[str, dict[str, Any]]:
    """Upload the Runner and every app's signed pack; return {app id: manifest pack entry}."""
    public = public_key_hex(private_key_pem)
    if trusted_keys(trusted_file).get(key_id) != public:
        raise KeyNotTrusted(
            f"the signing key {key_id!r} is not in build/trusted_keys.json, so the Runner would "
            f'refuse its packs. Add "{key_id}": "{public}" (a public key) in a PR.'
        )
    entries: dict[str, dict[str, Any]] = {}
    with tempfile.TemporaryDirectory(prefix="makemyexe-packs-") as tmp:
        work = Path(tmp)
        version, runner_dir = runner_from_release(release_dir, work)
        runner_prefix = f"runner/{version}"
        runner_layout = zipblocks.make_runner_blocks(runner_dir, work / "runner-blocks")
        for name in ("exe.bin", "blocks.bin", "layout.json"):
            upload(
                work / "runner-blocks" / name, f"{runner_prefix}/{name}", "application/octet-stream"
            )
        pointer = work / f"latest-{RUNNER_MAJOR}.json"
        pointer.write_text(json.dumps({"version": version, "prefix": runner_prefix}))
        upload(pointer, f"runner/latest-{RUNNER_MAJOR}.json", "application/json")
        print(f"uploaded {runner_prefix} ({runner_layout['size'] / 1_000_000:.1f} MB of blocks)")

        for app in apps:
            source = automations_dir / app["id"]
            pack = build_pack.make_pack(
                source, work / "packs" / app["id"], "catalog", key_id, private_key_pem, version
            )
            prefix = f"packs/catalog/{app['id']}/{app['version']}"
            blocks_dir = work / "blocks" / app["id"]
            layout = zipblocks.make_blocks(
                [("app.mmx", pack), ("Guide.pdf", app["guide"])], blocks_dir
            )
            upload(pack, f"{prefix}/app.mmx", "application/octet-stream")
            upload(app["guide"], f"{prefix}/Guide.pdf", "application/pdf")
            for name in ("blocks.bin", "layout.json"):
                upload(blocks_dir / name, f"{prefix}/{name}", "application/octet-stream")
            entries[app["id"]] = {
                "prefix": prefix,
                "runner": runner_prefix,
                "layers": [],
                "exe": app["exe"],
                "size_bytes": download_size(runner_layout, [layout], f"{app['exe']}.exe"),
                "pack_bytes": pack.stat().st_size,
            }
            print(f"uploaded {prefix} (pack {pack.stat().st_size} bytes)")
    return entries
