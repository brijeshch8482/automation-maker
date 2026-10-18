"""Start menu shortcuts for installed automations (docs/DESKTOP_APP.md §2.3, §15: always).

    %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\MakeMyEXE\\<Title>.lnk
        -> MakeMyEXE.exe --run <id>

The folder is ours (the installer makes it and removes it on uninstall), so a shortcut there may
be replaced. The .lnk is written here by hand (MS-SHLLINK: header, LinkInfo with the local path,
then the strings), so the app needs no COM, PowerShell or extra library.
"""

from __future__ import annotations

import os
import re
import struct
import sys
from pathlib import Path

FOLDER_NAME = "MakeMyEXE"
LINK_CLSID = bytes.fromhex("0114020000000000c000000000000046")
HAS_LINK_INFO, HAS_NAME, HAS_WORKING_DIR, HAS_ARGUMENTS, HAS_ICON, IS_UNICODE = (
    0x02,
    0x04,
    0x10,
    0x20,
    0x40,
    0x80,
)
FILE_ATTRIBUTE_ARCHIVE = 0x20
SW_SHOWNORMAL = 1
DRIVE_FIXED = 3
UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')


def start_menu_dir() -> Path | None:
    """Our Start menu folder, or None where there is no Start menu (not Windows)."""
    appdata = os.environ.get("APPDATA")
    if sys.platform != "win32" or not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / FOLDER_NAME


def shortcut_name(title: str, automation_id: str) -> str:
    name = UNSAFE.sub(" ", title).strip(" .") or automation_id
    return f"{name[:80]}.lnk"


def _string(value: str) -> bytes:
    data = value.encode("utf-16-le")
    return struct.pack("<H", len(data) // 2) + data


def link_bytes(target: Path, arguments: str, description: str, icon: Path | None = None) -> bytes:
    """A shell link to `target` (an absolute local path) with these arguments."""
    target_text = str(target)
    working_dir = str(target.parent)
    flags = HAS_LINK_INFO | HAS_NAME | HAS_WORKING_DIR | HAS_ARGUMENTS | HAS_ICON | IS_UNICODE
    header = (
        struct.pack("<I", 0x4C)
        + LINK_CLSID
        + struct.pack("<II", flags, FILE_ATTRIBUTE_ARCHIVE)
        + bytes(24)  # creation, access, write times: unknown
        + struct.pack("<IiIHHII", 0, 0, SW_SHOWNORMAL, 0, 0, 0, 0)
    )
    assert len(header) == 0x4C

    volume = struct.pack("<IIII", 17, DRIVE_FIXED, 0, 16) + b"\0"
    ansi = target_text.encode("mbcs" if sys.platform == "win32" else "latin-1", "replace") + b"\0"
    unicode_path = target_text.encode("utf-16-le") + b"\0\0"
    header_size = 0x24
    volume_at = header_size
    base_at = volume_at + len(volume)
    suffix_at = base_at + len(ansi)
    base_unicode_at = suffix_at + 1
    suffix_unicode_at = base_unicode_at + len(unicode_path)
    size = suffix_unicode_at + 2
    link_info = (
        struct.pack(
            "<IIIIIIIII",
            size,
            header_size,
            0x1,  # VolumeIDAndLocalBasePath
            volume_at,
            base_at,
            0,  # no network path
            suffix_at,
            base_unicode_at,
            suffix_unicode_at,
        )
        + volume
        + ansi
        + b"\0"
        + unicode_path
        + b"\0\0"
    )
    assert len(link_info) == size

    strings = (
        _string(description)
        + _string(working_dir)
        + _string(arguments)
        + _string(str(icon or target))
    )
    return header + link_info + strings + struct.pack("<I", 0)  # terminal block


def write_shortcut(
    folder: Path,
    title: str,
    automation_id: str,
    exe: Path,
    icon: Path | None = None,
) -> Path:
    """Create or replace the Start menu entry that runs this automation."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / shortcut_name(title, automation_id)
    data = link_bytes(exe, f"--run {automation_id}", f"{title} (MakeMyEXE)", icon)
    tmp = path.with_suffix(".lnk.tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return path
