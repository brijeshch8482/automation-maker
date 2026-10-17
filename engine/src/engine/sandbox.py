"""Runtime confinement for generated custom steps (ARCHITECTURE.md §8).

tools.check_job rejects custom_step.py code that imports anything outside its allowlist; this is
the backstop for what static checks can't see, such as a library call that writes to a path
(`image.save("C:/...")`). While a custom step runs, an audit hook (PEP 578, which can't be
removed once added) refuses:

- opening a file for writing anywhere but the output folder;
- deleting, renaming, moving or changing the permissions of any file;
- starting programs, loading native libraries, and network connections.

Reading files stays allowed: the step reads the files the user selected, and with the network
blocked nothing it reads can leave the PC. The hook is process-wide (threads too), and the
engine is single-step at a time, so a flag is enough to know a custom step is running.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from engine.errors import EngineError

WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT | os.O_TRUNC
# Always refused while a custom step runs.
DENIED = {
    "os.remove": "delete a file",
    "os.rmdir": "delete a folder",
    "shutil.rmtree": "delete a folder",
    "os.rename": "rename or move a file",
    "os.truncate": "change a file",
    "os.chmod": "change file permissions",
    "os.chown": "change file permissions",
    "os.chflags": "change file permissions",
    "os.symlink": "create a link",
    "os.link": "create a link",
    "os.utime": "change a file",
    "os.system": "start a program",
    "os.exec": "start a program",
    "os.posix_spawn": "start a program",
    "os.spawn": "start a program",
    "os.fork": "start a program",
    "os.forkpty": "start a program",
    "os.startfile": "start a program",
    "os.kill": "stop a program",
    "subprocess.Popen": "start a program",
    "ctypes.dlopen": "load a native library",
    "ctypes.dlsym": "load a native library",
    "winreg.CreateKey": "change the registry",
    "winreg.SetValue": "change the registry",
    "winreg.DeleteKey": "change the registry",
    "socket.connect": "use the internet",
    "socket.getaddrinfo": "use the internet",
}
# Network events stay allowed when the spec declares network.required (the offline guard in
# engine.guards covers the other case at start-up).
NETWORK_EVENTS = {"socket.connect", "socket.getaddrinfo"}

_state: dict[str, Any] = {"installed": False, "output_dir": None, "network": False}


class SandboxError(EngineError, PermissionError):
    """Also a PermissionError, so library code that tolerates an unwritable path (such as
    Python's own bytecode cache) carries on, and nothing is written."""

    def __init__(self, action: str) -> None:
        super().__init__(f"the custom step tried to {action}, which automations may not do")


def _within_output(path: Any) -> bool:
    output: Path | None = _state["output_dir"]
    if output is None or isinstance(path, int):
        return False
    try:
        target = Path(os.fsdecode(path)).resolve()
    except (TypeError, ValueError, OSError):
        return False
    return target == output or output in target.parents


def _hook(event: str, args: tuple[Any, ...]) -> None:
    if _state["output_dir"] is None:
        return
    if event == "open":
        path, mode, flags = (*args, None, None, None)[:3]
        writes = (isinstance(mode, str) and any(c in mode for c in "wax+")) or (
            isinstance(flags, int) and flags & WRITE_FLAGS
        )
        if writes and not _within_output(path):
            raise SandboxError("write a file outside the output folder")
    elif event == "os.mkdir":
        if not _within_output(args[0]):
            raise SandboxError("create a folder outside the output folder")
    elif event in DENIED:
        if event in NETWORK_EVENTS and _state["network"]:
            return
        raise SandboxError(DENIED[event])


@contextmanager
def confined(output_dir: Path, network: bool = False) -> Iterator[None]:
    """Run a custom step: writes only into `output_dir`, no deletes, programs or libraries."""
    if not _state["installed"]:
        sys.addaudithook(_hook)
        _state["installed"] = True
    output_dir.mkdir(parents=True, exist_ok=True)
    previous = (_state["output_dir"], _state["network"])
    _state["output_dir"], _state["network"] = output_dir.resolve(), network
    try:
        yield
    finally:
        _state["output_dir"], _state["network"] = previous
