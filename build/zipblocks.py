"""Zip entry blocks: the Runner, layers and packs as ready-made pieces of a zip (§8.6).

    python -m build.zipblocks runner <runner_folder> --out <dir>
    python -m build.zipblocks files --out <dir> NAME=PATH [NAME=PATH ...]

A block is the local-file part of a zip (headers + compressed data, back to back) in
`blocks.bin`, with `layout.json` listing what a central directory needs for each entry. The
download Worker (worker/) streams Runner + layers + pack blocks unchanged into one zip and only
writes the central directory, so it never compresses or even reads the bytes. The Runner's exe
is kept apart (`exe.bin`: its compressed data only), because each app renames it (`MakePDF.exe`);
the Worker writes that one local header itself.

Made only by trusted publish steps, from files they built or checked. Standard library only.
"""

from __future__ import annotations

import argparse
import json
import shutil
import struct
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any

FORMAT = 1
ZIP_TIME = (2020, 1, 1, 0, 0, 0)
LOCAL_HEADER = struct.Struct("<IHHHHHIIIHH")  # 30 bytes
LOCAL_SIG = 0x04034B50
MAX_ENTRY = 0xFFFFFFFF - 1  # no Zip64: every entry and the whole zip stay under 4 GB
EXE_NAME = "MakeMyEXE.exe"


class BlockError(Exception):
    pass


def _entry_layout(info: zipfile.ZipInfo, offset: int) -> dict[str, Any]:
    time = (info.date_time[3] << 11) | (info.date_time[4] << 5) | (info.date_time[5] // 2)
    date = ((info.date_time[0] - 1980) << 9) | (info.date_time[1] << 5) | info.date_time[2]
    return {
        "name": info.filename,
        "offset": offset,
        "crc": info.CRC,
        "csize": info.compress_size,
        "usize": info.file_size,
        "method": info.compress_type,
        "time": time,
        "date": date,
        "flags": info.flag_bits & ~0x08,
        "version": max(info.extract_version, 20),
        "external_attr": info.external_attr,
    }


def _write_zip(entries: list[tuple[str, Path]], target: Path) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, source in entries:
            if "\\" in name or name.startswith("/") or ".." in name.split("/"):
                raise BlockError(f"bad entry name {name!r}")
            if source.stat().st_size > MAX_ENTRY:
                raise BlockError(f"{name} is too large for a zip without Zip64")
            info = zipfile.ZipInfo(name, ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            with source.open("rb") as src, archive.open(info, "w") as dst:
                shutil.copyfileobj(src, dst, 1 << 20)


def _read_entries(zip_path: Path) -> tuple[list[zipfile.ZipInfo], int]:
    with zipfile.ZipFile(zip_path) as archive:
        infos = sorted(archive.infolist(), key=lambda i: i.header_offset)
        return infos, archive.start_dir


def _data_offset(fh, info: zipfile.ZipInfo) -> int:
    fh.seek(info.header_offset)
    fields = LOCAL_HEADER.unpack(fh.read(LOCAL_HEADER.size))
    if fields[0] != LOCAL_SIG:
        raise BlockError("not a local file header")
    return info.header_offset + LOCAL_HEADER.size + fields[9] + fields[10]


def make_blocks(entries: list[tuple[str, Path]], out: Path) -> dict[str, Any]:
    """blocks.bin + layout.json in `out` for these (zip name, source file) entries."""
    out.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="makemyexe-blocks-") as tmp:
        zip_path = Path(tmp) / "all.zip"
        _write_zip(entries, zip_path)
        infos, start_dir = _read_entries(zip_path)
        with zip_path.open("rb") as src, (out / "blocks.bin").open("wb") as dst:
            _copy_range(src, dst, 0, start_dir)
    layout = {
        "format": FORMAT,
        "size": start_dir,
        "entries": [_entry_layout(info, info.header_offset) for info in infos],
    }
    (out / "layout.json").write_text(json.dumps(layout, indent=1), encoding="utf-8")
    return layout


def make_runner_blocks(folder: Path, out: Path) -> dict[str, Any]:
    """The Runner folder as exe.bin (the exe's compressed data) plus blocks for the rest."""
    exe = folder / EXE_NAME
    if not exe.is_file():
        raise BlockError(f"{EXE_NAME} is missing from {folder}")
    rest = [
        (path.relative_to(folder).as_posix(), path)
        for path in sorted(folder.rglob("*"))
        if path.is_file() and not path.is_symlink() and path != exe
    ]
    layout = make_blocks(rest, out)
    with tempfile.TemporaryDirectory(prefix="makemyexe-exe-") as tmp:
        zip_path = Path(tmp) / "exe.zip"
        _write_zip([(EXE_NAME, exe)], zip_path)
        (info,), _ = _read_entries(zip_path)
        with zip_path.open("rb") as src, (out / "exe.bin").open("wb") as dst:
            start = _data_offset(src, info)
            _copy_range(src, dst, start, start + info.compress_size)
    layout["exe"] = {k: v for k, v in _entry_layout(info, 0).items() if k not in ("name", "offset")}
    (out / "layout.json").write_text(json.dumps(layout, indent=1), encoding="utf-8")
    return layout


def _copy_range(src, dst, start: int, end: int) -> None:
    src.seek(start)
    remaining = end - start
    while remaining:
        chunk = src.read(min(remaining, 1 << 20))
        if not chunk:
            raise BlockError("unexpected end of zip")
        dst.write(chunk)
        remaining -= len(chunk)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m build.zipblocks", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    runner = sub.add_parser("runner", help="blocks for a built Runner folder")
    runner.add_argument("folder", type=Path)
    runner.add_argument("--out", type=Path, required=True)
    files = sub.add_parser("files", help="blocks for named files (a pack, a layer)")
    files.add_argument("--out", type=Path, required=True)
    files.add_argument("entries", nargs="+", metavar="NAME=PATH")
    args = parser.parse_args(argv)
    try:
        if args.command == "runner":
            layout = make_runner_blocks(args.folder, args.out)
        else:
            pairs = [e.split("=", 1) for e in args.entries]
            if any(len(p) != 2 for p in pairs):
                raise BlockError("entries are NAME=PATH")
            layout = make_blocks([(name, Path(path)) for name, path in pairs], args.out)
    except (BlockError, OSError) as err:
        print(f"error: {err}", file=sys.stderr)
        return 1
    print(f"{len(layout['entries'])} entries, {layout['size']} bytes in {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
