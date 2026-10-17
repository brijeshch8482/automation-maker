"""AI generation behind one interface (ARCHITECTURE.md §11). Nothing outside this package may
depend on which provider is active."""

from api.providers.base import (
    FireRejected,
    FireUnknown,
    GenerationProvider,
    JobContext,
    RetryLater,
    RunRef,
)

__all__ = [
    "FireRejected",
    "FireUnknown",
    "GenerationProvider",
    "JobContext",
    "RetryLater",
    "RunRef",
]
