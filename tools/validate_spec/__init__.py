"""CLI wrapper around `spec.validate`: `python -m tools.validate_spec <file> [<file> ...]`."""

from spec.validate import Issue, format_loc, validate_spec

__all__ = ["Issue", "format_loc", "validate_spec"]
