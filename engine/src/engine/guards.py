"""Offline guard: with network.required = false, any attempt to open a network connection fails.

Installed once at EXE start-up (ARCHITECTURE.md §8). Generated code is also checked statically for
network imports by tools.check_job; this is the runtime backstop.
"""

from __future__ import annotations

import socket
from typing import Any

from engine.errors import EngineError


class OfflineError(EngineError):
    def __init__(self) -> None:
        super().__init__("this automation works offline and may not use the internet")


def _blocked(*_args: Any, **_kwargs: Any) -> Any:
    raise OfflineError()


_ORIGINALS: dict[str, Any] = {}


def block_network() -> None:
    if _ORIGINALS:
        return
    _ORIGINALS.update(
        connect=socket.socket.connect,
        connect_ex=socket.socket.connect_ex,
        sendto=socket.socket.sendto,
        create_connection=socket.create_connection,
        getaddrinfo=socket.getaddrinfo,
    )
    socket.socket.connect = _blocked  # type: ignore[method-assign]
    socket.socket.connect_ex = _blocked  # type: ignore[method-assign]
    socket.socket.sendto = _blocked  # type: ignore[method-assign]
    socket.create_connection = _blocked  # type: ignore[assignment]
    socket.getaddrinfo = _blocked  # type: ignore[assignment]


def unblock_network() -> None:
    """For tests only."""
    if not _ORIGINALS:
        return
    socket.socket.connect = _ORIGINALS["connect"]  # type: ignore[method-assign]
    socket.socket.connect_ex = _ORIGINALS["connect_ex"]  # type: ignore[method-assign]
    socket.socket.sendto = _ORIGINALS["sendto"]  # type: ignore[method-assign]
    socket.create_connection = _ORIGINALS["create_connection"]
    socket.getaddrinfo = _ORIGINALS["getaddrinfo"]
    _ORIGINALS.clear()
