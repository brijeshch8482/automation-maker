"""Engine errors and the "Copy error report" text.

The report must never contain input values, settings or file contents (ARCHITECTURE.md §1.6),
so only EngineError messages (written by us, value-free) are included; any other exception is
reported by type and code location only.
"""

from __future__ import annotations

import platform
import sys
import traceback

from engine import __version__


class EngineError(Exception):
    """An expected failure with a user-facing message that contains no user data."""


class StepError(EngineError):
    def __init__(self, index: int, block: str, cause: BaseException) -> None:
        message = str(cause) if isinstance(cause, EngineError) else "the step failed unexpectedly"
        super().__init__(f"Step {index + 1} ({block}): {message}")
        self.index = index
        self.block = block
        self.cause = cause


def error_report(error: BaseException, spec_id: str, spec_version: str) -> str:
    cause = error.cause if isinstance(error, StepError) else error
    lines = [
        "MakeMyEXE error report",
        f"automation: {spec_id} {spec_version}",
        f"engine: {__version__}",
        f"system: {platform.system()} {platform.release()}, Python {sys.version.split()[0]}",
        f"error: {type(cause).__name__}",
    ]
    if isinstance(error, StepError):
        lines.append(f"step: {error.index + 1} ({error.block})")
    if isinstance(cause, EngineError):
        lines.append(f"message: {cause}")
    lines.append("trace:")
    for frame in traceback.extract_tb(cause.__traceback__):
        # File name and line only: no source lines, locals or argument values.
        filename = frame.filename.replace("\\", "/").rsplit("/", 1)[-1]
        lines.append(f"  {filename}:{frame.lineno} in {frame.name}")
    return "\n".join(lines)
