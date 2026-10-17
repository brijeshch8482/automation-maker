"""Copy the build snapshot of automation-maker into a checkout of automation-builds.

    python3 builds-repo/sync.py --target <automation-builds checkout> --version <tag> --commit <sha>

Run by .github/workflows/sync-builds.yml. Only the managed paths below are replaced; anything
else in the target (its git history, job branches) is left alone. Standard library only.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parent.parent

# automation-maker path -> automation-builds path
MANAGED = {
    "engine": "engine",
    "spec": "spec",
    "tools": "tools",
    "build": "build",
    "pyproject.toml": "pyproject.toml",
    "uv.lock": "uv.lock",
    # The workspace lists api; uv needs its pyproject.toml, never its code.
    "api/pyproject.toml": "api/pyproject.toml",
    "builds-repo/README.md": "README.md",
    # For the am-spec / am-build routines, which work in automation-builds: their instructions,
    # the spec guide, and examples (the catalog, plus a job with a custom step).
    "builds-repo/CLAUDE.md": "CLAUDE.md",
    "docs/SPEC_GUIDE.md": "docs/SPEC_GUIDE.md",
    "automations": "examples/catalog",
    "tests/fixtures/jobs/word-count": "examples/custom/word-count",
    "builds-repo/gitignore": ".gitignore",
    "builds-repo/.github/workflows/build.yml": ".github/workflows/build.yml",
}
IGNORE = shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".ruff_cache")


def sync(target: Path, version: str, commit: str, source: Path = SOURCE) -> list[str]:
    if not (target / ".git").exists():
        raise SystemExit(f"{target} is not a git checkout")
    copied = []
    for src_rel, dst_rel in MANAGED.items():
        src, dst = source / src_rel, target / dst_rel
        if dst.is_dir():
            shutil.rmtree(dst)
        elif dst.exists():
            dst.unlink()
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst, ignore=IGNORE)
        else:
            shutil.copy2(src, dst)
        copied.append(dst_rel)
    (target / "ENGINE_VERSION").write_text(f"{version} {commit[:12]}\n", encoding="utf-8")
    return copied


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--target", type=Path, required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--commit", required=True)
    args = parser.parse_args(argv)
    for path in sync(args.target, args.version, args.commit):
        print(f"synced {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
