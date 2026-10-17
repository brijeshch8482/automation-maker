"""Checks for a generated job folder (jobs/<id>/) before it may be pushed and built.

    python -m tools.check_job jobs/<id> [--json]

Run by the `am-build` routine on Linux (docs/ROUTINES.md §3) and by our tests on every catalog
automation. The folder may hold only spec.json, custom_step.py + test_custom_step.py (both
exactly when a step is custom.step) and small, inert sample files in samples/.

Checks, in order: layout, spec (validate_spec + sample files), code (AST rules: allowlisted
imports, no dynamic code, no dunder tricks), ruff, bandit, pytest, smoke_test (the engine on
sample_data, with engine.sandbox confining the custom step). Exit 0 when all pass, else 1.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from collections.abc import Collection, Iterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from spec.validate import validate_spec

SPEC_FILE = "spec.json"
CODE_FILE = "custom_step.py"
TEST_FILE = "test_custom_step.py"
SAMPLES_DIR = "samples"

MAX_CODE_BYTES = 100_000
MAX_SAMPLE_FILES = 30
MAX_SAMPLE_BYTES = 2_000_000
MAX_SAMPLES_TOTAL = 8_000_000
SAMPLE_EXTENSIONS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tif", ".tiff", ".webp", ".heic",
    ".txt", ".csv", ".tsv", ".json", ".md", ".xlsx", ".docx",
}  # fmt: skip
LOG_TAIL_CHARS = 4_000
TIMEOUT_S = {"ruff": 60, "bandit": 120, "pytest": 300, "smoke_test": 300}

# Top-level modules custom_step.py may import. Pure computation, text and data formats, and the
# engine's own document libraries. Nothing that touches the OS, processes, threads or the net.
CODE_MODULES = {
    "__future__", "base64", "bisect", "calendar", "cmath", "collections", "copy", "csv",
    "dataclasses", "datetime", "decimal", "difflib", "enum", "fractions", "functools",
    "hashlib", "heapq", "html", "io", "itertools", "json", "math", "numbers", "operator",
    "random", "re", "statistics", "string", "textwrap", "typing", "unicodedata", "zlib",
    "fpdf", "PIL", "pillow_heif", "pypdf",
}  # fmt: skip
# Allowed only as `from <module> import <name>` with these names.
CODE_FROM_IMPORTS = {
    "engine.custom_api": {"CustomContext"},
    "pathlib": {"PurePath", "PurePosixPath", "PureWindowsPath"},
}
# With network.required = true (and its domains in the spec), also these.
NETWORK_MODULES = {"urllib", "http"}
# The test file may also use pytest, pathlib and the engine's test helpers.
TEST_MODULES = CODE_MODULES | {"pytest", "pathlib"}
TEST_FROM_IMPORTS = {
    **CODE_FROM_IMPORTS,
    "pathlib": {"Path", "PurePath", "PurePosixPath", "PureWindowsPath"},
    "engine.testing": {
        "load_custom_step",
        "run_custom_step",
        "sample_context",
        "sample_run_context",
    },
    "engine.values": {"Document", "SavedFile"},
    "engine.errors": {"EngineError"},
    "engine.sandbox": {"SandboxError"},
}
FORBIDDEN_CALLS = {
    "__import__", "breakpoint", "compile", "delattr", "eval", "exec", "getattr", "globals",
    "input", "locals", "open", "setattr", "vars", "memoryview",
}  # fmt: skip
ALLOWED_DUNDERS = {"__name__", "__file__", "__init__", "__post_init__", "__repr__", "__str__"}


@dataclass
class Check:
    name: str
    status: str = "passed"  # passed | failed | skipped
    problems: list[str] = field(default_factory=list)
    command: str | None = None
    log_tail: str | None = None

    def fail(self, problem: str) -> None:
        self.status = "failed"
        self.problems.append(problem)


@dataclass
class JobReport:
    folder: str
    status: str = "passed"
    used_custom_step: bool = False
    checks: list[Check] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# --- Layout -----------------------------------------------------------------------------


def check_layout(folder: Path, has_custom: bool | None) -> Iterator[str]:
    if not folder.is_dir():
        yield f"{folder} is not a folder"
        return
    for path in sorted(folder.rglob("*")):
        rel = path.relative_to(folder).as_posix()
        if any(part in ("__pycache__", ".pytest_cache") for part in path.parts):
            continue  # left behind by a local test run; never bundled
        if path.is_symlink():
            yield f"{rel}: links are not allowed"
        elif rel in (SPEC_FILE, CODE_FILE, TEST_FILE, SAMPLES_DIR):
            continue
        elif rel.startswith(SAMPLES_DIR + "/"):
            if path.is_file() and path.suffix.lower() not in SAMPLE_EXTENSIONS:
                yield f"{rel}: sample files may only be documents, images or text"
        else:
            yield f"{rel}: only {SPEC_FILE}, {CODE_FILE}, {TEST_FILE} and samples/ belong here"

    if not (folder / SPEC_FILE).is_file():
        yield f"{SPEC_FILE} is missing"
    samples = [p for p in (folder / SAMPLES_DIR).rglob("*") if p.is_file()]
    if len(samples) > MAX_SAMPLE_FILES:
        yield f"{SAMPLES_DIR}/ has {len(samples)} files; at most {MAX_SAMPLE_FILES}"
    sizes = [p.stat().st_size for p in samples if not p.is_symlink()]
    for path, size in zip(samples, sizes, strict=False):
        if size > MAX_SAMPLE_BYTES:
            yield f"{path.relative_to(folder).as_posix()}: sample files must be under 2 MB"
    if sum(sizes) > MAX_SAMPLES_TOTAL:
        yield f"{SAMPLES_DIR}/ is over 8 MB in total"

    if has_custom is None:
        return
    for name in (CODE_FILE, TEST_FILE):
        exists = (folder / name).is_file()
        if has_custom and not exists:
            yield f"{name} is missing; the spec has a custom.step"
        elif not has_custom and exists:
            yield f"{name} must not exist; the spec has no custom.step"
        elif exists and (folder / name).stat().st_size > MAX_CODE_BYTES:
            yield f"{name} is over 100 KB"


# --- Spec -------------------------------------------------------------------------------


def load_job_spec(folder: Path) -> tuple[dict[str, Any] | None, list[str]]:
    try:
        data = json.loads((folder / SPEC_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError) as err:
        return None, [f"{SPEC_FILE} could not be read: {err}"]
    spec, issues = validate_spec(data)
    if spec is None or issues:
        return None, [str(i) for i in issues]
    problems = []
    try:
        from engine.loader import load_spec

        loaded = load_spec(folder / SPEC_FILE)
        loaded.sample_inputs()
        loaded.sample_settings()
    except Exception as err:  # EngineError: a missing sample file or a bad path
        problems.append(str(err))
    for path in _sample_paths(data):
        if not Path(path).parts or Path(path).parts[0] != SAMPLES_DIR:
            problems.append(f"sample_data path {path!r} must be inside {SAMPLES_DIR}/")
    return data, problems


def _sample_paths(data: dict[str, Any]) -> Iterator[str]:
    sample = data.get("sample_data") or {}
    for section in ("settings", "inputs"):
        for f in data.get(section) or []:
            value = sample.get(f.get("key"))
            if f.get("type") in ("file", "image_file", "folder") and isinstance(value, str):
                yield value
            elif f.get("type") == "files" and isinstance(value, list):
                yield from (v for v in value if isinstance(v, str))


def custom_functions(data: dict[str, Any]) -> set[str]:
    return {
        (step.get("args") or {}).get("function", "run")
        for step in data.get("steps") or []
        if step.get("block") == "custom.step"
    }


# --- Code rules -------------------------------------------------------------------------


def check_code(
    source: str,
    filename: str,
    modules: set[str],
    from_imports: dict[str, set[str]],
    required_functions: Collection[str] = (),
) -> Iterator[str]:
    try:
        tree = ast.parse(source, filename=filename)
    except SyntaxError as err:
        yield f"{filename}:{err.lineno}: syntax error: {err.msg}"
        return

    def where(node: ast.AST) -> str:
        return f"{filename}:{getattr(node, 'lineno', 0)}"

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".")[0]
                if top not in modules:
                    yield f"{where(node)}: import {alias.name} is not allowed"
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                yield f"{where(node)}: relative imports are not allowed"
                continue
            module = node.module or ""
            names = {a.name for a in node.names}
            if module in from_imports:
                extra = names - from_imports[module]
                if extra:
                    listed = ", ".join(sorted(extra))
                    yield f"{where(node)}: from {module} import {listed} is not allowed"
            elif module.split(".")[0] not in modules:
                yield f"{where(node)}: from {module} import ... is not allowed"
            elif "*" in names:
                yield f"{where(node)}: import * is not allowed"
        elif isinstance(node, ast.Name):
            dunder = _is_dunder(node.id) and node.id not in ALLOWED_DUNDERS
            if node.id in FORBIDDEN_CALLS or dunder:
                yield f"{where(node)}: {node.id} is not allowed"
        elif isinstance(node, ast.Attribute):
            if _is_dunder(node.attr) and node.attr not in ALLOWED_DUNDERS:
                yield f"{where(node)}: .{node.attr} is not allowed"
        elif isinstance(node, ast.Global | ast.Nonlocal):
            yield f"{where(node)}: global and nonlocal are not allowed"

    defined = {
        n.name
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and len(n.args.args) + len(n.args.posonlyargs) >= 1
    }
    for name in sorted(set(required_functions) - defined):
        yield f"{filename}: the spec calls {name}(ctx), but it is not defined at the top level"


def _is_dunder(name: str) -> bool:
    return len(name) > 4 and name.startswith("__") and name.endswith("__")


# --- Tools ------------------------------------------------------------------------------


def run_tool(check: Check, cmd: list[str], cwd: Path) -> None:
    check.command = " ".join(_display(c) for c in cmd)
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "QT_QPA_PLATFORM": "offscreen"}
    try:
        result = subprocess.run(
            cmd,
            cwd=cwd,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=TIMEOUT_S[check.name],
            check=False,
        )
    except FileNotFoundError:
        check.fail(f"{cmd[0]} is not installed (uv sync --only-group dev --inexact)")
        return
    except subprocess.TimeoutExpired:
        check.fail(f"timed out after {TIMEOUT_S[check.name]} s")
        return
    if result.returncode != 0:
        check.fail(f"exit code {result.returncode}")
        check.log_tail = (result.stdout + result.stderr)[-LOG_TAIL_CHARS:]


def _display(arg: str) -> str:
    if arg == sys.executable:
        return "python"
    return arg


# --- Everything -------------------------------------------------------------------------


def check_job(folder: Path, repo_root: Path | None = None) -> JobReport:
    folder = folder.resolve()
    root = repo_root or Path(__file__).resolve().parents[2]
    report = JobReport(folder=_relative(folder, root))
    checks = {name: Check(name) for name in ("layout", "spec", "code", *TIMEOUT_S)}
    report.checks = list(checks.values())

    data = None
    if (folder / SPEC_FILE).is_file():
        data, problems = load_job_spec(folder)
        for problem in problems:
            checks["spec"].fail(problem)
    else:
        checks["spec"].fail(f"{SPEC_FILE} is missing")
    functions = custom_functions(data) if data else set()
    report.used_custom_step = bool(functions)
    for problem in check_layout(folder, bool(functions) if data else None):
        checks["layout"].fail(problem)

    code_files = [n for n in (CODE_FILE, TEST_FILE) if (folder / n).is_file()]
    if data and functions and checks["layout"].status == "passed":
        network = bool((data.get("network") or {}).get("required"))
        extra = NETWORK_MODULES if network else set()
        rules = {
            CODE_FILE: (CODE_MODULES | extra, CODE_FROM_IMPORTS, functions),
            TEST_FILE: (TEST_MODULES | extra, TEST_FROM_IMPORTS, set()),
        }
        for name in code_files:
            modules, from_imports, required = rules[name]
            source = (folder / name).read_text(encoding="utf-8", errors="replace")
            for problem in check_code(source, name, modules, from_imports, required):
                checks["code"].fail(problem)
    else:
        checks["code"].status = "skipped"

    if any(c.status == "failed" for c in (checks["layout"], checks["spec"], checks["code"])):
        for name in TIMEOUT_S:
            checks[name].status = "skipped"
    else:
        py = sys.executable
        files = [str(folder / n) for n in code_files]
        if files:
            run_tool(checks["ruff"], [py, "-m", "ruff", "check", "--no-cache", *files], root)
            run_tool(checks["bandit"], [py, "-m", "bandit", "-q", "-ll", *files], root)
            run_tool(
                checks["pytest"],
                [py, "-m", "pytest", "-q", "-p", "no:cacheprovider", str(folder / TEST_FILE)],
                root,
            )
        else:
            for name in ("ruff", "bandit", "pytest"):
                checks[name].status = "skipped"
        run_tool(
            checks["smoke_test"],
            [py, "-m", "engine", str(folder / SPEC_FILE), "--smoke-test"],
            root,
        )

    if any(c.status == "failed" for c in report.checks):
        report.status = "failed"
    return report


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)
