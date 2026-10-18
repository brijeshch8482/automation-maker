"""Start menu shortcuts for installed automations (docs/DESKTOP_APP.md §2.3, §15: always).

    %APPDATA%\\Microsoft\\Windows\\Start Menu\\Programs\\MakeMyEXE\\<Title>.lnk
        -> MakeMyEXE.exe --run <id>

The folder is ours (the installer makes it and removes it on uninstall), so a shortcut there may
be replaced. Windows writes the .lnk itself through the Shell's IShellLinkW, called with ctypes:
no PowerShell (offices may lock it down) and no extra library.
"""

from __future__ import annotations

import os
import re
import sys
import uuid
from pathlib import Path

FOLDER_NAME = "MakeMyEXE"
UNSAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')
CLSID_SHELL_LINK = "00021401-0000-0000-C000-000000000046"
IID_SHELL_LINK_W = "000214F9-0000-0000-C000-000000000046"
IID_PERSIST_FILE = "0000010B-0000-0000-C000-000000000046"
# Vtable slots: IUnknown 0-2, then the interface's methods in declaration order.
RELEASE = 2
SET_DESCRIPTION, SET_WORKING_DIRECTORY, SET_ARGUMENTS = 7, 9, 11
SET_ICON_LOCATION, SET_PATH = 17, 20
QUERY_INTERFACE, PERSIST_SAVE = 0, 6


def start_menu_dir() -> Path | None:
    """Our Start menu folder, or None where there is no Start menu (not Windows)."""
    appdata = os.environ.get("APPDATA")
    if sys.platform != "win32" or not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / FOLDER_NAME


def shortcut_name(title: str, automation_id: str) -> str:
    name = UNSAFE.sub(" ", title).strip(" .") or automation_id
    return f"{name[:80]}.lnk"


def write_shortcut(
    folder: Path, title: str, automation_id: str, exe: Path, icon: Path | None = None
) -> Path:
    """Create or replace the Start menu entry that runs this automation (Windows only)."""
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / shortcut_name(title, automation_id)
    _save_link(
        path,
        target=exe,
        arguments=f"--run {automation_id}",
        description=f"{title} (MakeMyEXE)",
        icon=icon or exe,
    )
    return path


def _save_link(path: Path, target: Path, arguments: str, description: str, icon: Path) -> None:
    import ctypes
    from ctypes import HRESULT, POINTER, WINFUNCTYPE, byref, c_int, c_void_p, c_wchar_p

    class GUID(ctypes.Structure):
        _fields_ = [("bytes", ctypes.c_ubyte * 16)]

    def guid(text: str) -> GUID:
        value = GUID()
        ctypes.memmove(value.bytes, uuid.UUID(text).bytes_le, 16)
        return value

    def call(obj: c_void_p, slot: int, argtypes: tuple, *args: object) -> None:
        table = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
        WINFUNCTYPE(HRESULT, c_void_p, *argtypes)(table[slot])(obj, *args)  # raises on failure

    def release(obj: c_void_p) -> None:
        table = ctypes.cast(obj, POINTER(POINTER(c_void_p)))[0]
        WINFUNCTYPE(ctypes.c_ulong, c_void_p)(table[RELEASE])(obj)

    ole32 = ctypes.windll.ole32  # type: ignore[attr-defined]
    # Qt has already set up COM on this thread when there's a window; then this is a no-op.
    initialized = ole32.CoInitializeEx(None, 0x2) in (0, 1)  # S_OK, S_FALSE
    link, persist = c_void_p(), c_void_p()
    try:
        clsid, iid = guid(CLSID_SHELL_LINK), guid(IID_SHELL_LINK_W)
        ctypes.OleDLL("ole32").CoCreateInstance(byref(clsid), None, 1, byref(iid), byref(link))
        call(link, SET_PATH, (c_wchar_p,), str(target))
        call(link, SET_ARGUMENTS, (c_wchar_p,), arguments)
        call(link, SET_WORKING_DIRECTORY, (c_wchar_p,), str(target.parent))
        call(link, SET_DESCRIPTION, (c_wchar_p,), description)
        call(link, SET_ICON_LOCATION, (c_wchar_p, c_int), str(icon), 0)
        persist_iid = guid(IID_PERSIST_FILE)
        call(
            link,
            QUERY_INTERFACE,
            (POINTER(GUID), POINTER(c_void_p)),
            byref(persist_iid),
            byref(persist),
        )
        call(persist, PERSIST_SAVE, (c_wchar_p, c_int), str(path), 1)
    finally:
        for obj in (persist, link):
            if obj.value:
                release(obj)
        if initialized:
            ole32.CoUninitialize()
