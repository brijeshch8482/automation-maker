"""tools.check_job: a generated job folder passes only if it stays inside the rules."""

import json
import os
import shutil
from pathlib import Path

import pytest

from tests.conftest import REPO_ROOT
from tools.check_job import (
    CODE_FROM_IMPORTS,
    CODE_MODULES,
    NETWORK_MODULES,
    check_code,
    check_job,
)
from tools.check_job.__main__ import main

FIXTURE = REPO_ROOT / "tests" / "fixtures" / "jobs" / "word-count"
CATALOG = sorted(p.parent for p in (REPO_ROOT / "automations").glob("*/spec.json"))


def statuses(report) -> dict[str, str]:
    return {c.name: c.status for c in report.checks}


def problems(report, name: str) -> str:
    return "\n".join(next(c for c in report.checks if c.name == name).problems)


@pytest.fixture
def job(tmp_path) -> Path:
    folder = tmp_path / "jobs" / "job_01TEST"
    shutil.copytree(FIXTURE, folder, ignore=shutil.ignore_patterns("__pycache__"))
    return folder


def edit_spec(folder: Path, change) -> None:
    path = folder / "spec.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("folder", CATALOG, ids=lambda p: p.name)
def test_every_catalog_automation_passes(folder):
    report = check_job(folder)
    assert report.status == "passed", report.to_dict()
    assert not report.used_custom_step
    assert statuses(report)["smoke_test"] == "passed"
    assert statuses(report)["pytest"] == "skipped"


def test_custom_step_job_passes_every_check(job, capsys):
    report = check_job(job)
    assert report.status == "passed", report.to_dict()
    assert report.used_custom_step
    assert set(statuses(report).values()) == {"passed"}
    assert main([str(job)]) == 0
    assert "PASSED" in capsys.readouterr().out


def test_json_report(job, capsys):
    (job / "notes.md").write_text("x")
    assert main([str(job), "--json"]) == 1
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "failed"
    layout = next(c for c in report["checks"] if c["name"] == "layout")
    assert "notes.md" in layout["problems"][0]


# --- Layout -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("make", "expected"),
    [
        (lambda j: (j / "helper.py").write_text("x = 1\n"), "helper.py: only"),
        (lambda j: (j / ".github").mkdir(), ".github: only"),
        (lambda j: (j / "samples" / "run.exe").write_bytes(b"MZ"), "run.exe: sample files"),
        (lambda j: (j / "samples" / "tool.py").write_text("x"), "tool.py: sample files"),
        (lambda j: (j / "custom_step.py").unlink(), "custom_step.py is missing"),
        (lambda j: (j / "test_custom_step.py").unlink(), "test_custom_step.py is missing"),
        (
            lambda j: (j / "samples" / "big.txt").write_bytes(b"x" * 2_100_000),
            "must be under 2 MB",
        ),
    ],
)
def test_layout_problems(job, make, expected):
    make(job)
    report = check_job(job)
    assert report.status == "failed"
    assert expected in problems(report, "layout")
    # Nothing is run once the folder breaks the rules.
    assert statuses(report)["smoke_test"] == "skipped"


@pytest.mark.skipif(os.name == "nt", reason="symlinks need extra rights on Windows")
def test_links_are_refused(job, tmp_path):
    (tmp_path / "secret.txt").write_text("x")
    (job / "samples" / "link.txt").symlink_to(tmp_path / "secret.txt")
    assert "links are not allowed" in problems(check_job(job), "layout")


def test_code_files_only_with_a_custom_step(job):
    counter = {"block": "counter.next", "args": {"name": "n", "prefix": "N-"}, "out": "n"}
    edit_spec(job, lambda d: d.update(steps=[counter], output={"type": "none"}))
    report = check_job(job)
    assert "custom_step.py must not exist" in problems(report, "layout")


# --- Spec ---------------------------------------------------------------------------------


def test_spec_must_validate(job):
    edit_spec(job, lambda d: d["network"].update(required=True))
    assert "list the exact domains" in problems(check_job(job), "spec")


def test_sample_files_must_exist_inside_samples(job):
    edit_spec(job, lambda d: d["sample_data"].update(text_file="samples/Missing.txt"))
    assert "missing next to spec.json" in problems(check_job(job), "spec")
    (job / "Notes.txt").write_text("x")
    edit_spec(job, lambda d: d["sample_data"].update(text_file="Notes.txt"))
    assert "must be inside samples/" in problems(check_job(job), "spec")


# --- Code rules ---------------------------------------------------------------------------


def code_problems(source: str, modules=CODE_MODULES, functions=("run",)) -> list[str]:
    return list(check_code(source, "custom_step.py", modules, CODE_FROM_IMPORTS, functions))


GOOD = "def run(ctx):\n    return ctx.document(b'x', 'txt')\n"


@pytest.mark.parametrize(
    "line",
    [
        "import os",
        "import subprocess",
        "import shutil",
        "import socket",
        "import urllib.request",
        "import threading",
        "import ctypes",
        "import importlib",
        "import sys",
        "from os import path",
        "from pathlib import Path",
        "import pathlib",
        "from . import helper",
        "from json import *",
        "x = eval('1')",
        "exec('x = 1')",
        "f = open('a.txt', 'w')",
        "m = __import__('os')",
        "g = globals()",
        "a = getattr(int, 'real')",
        "b = (1).__class__.__subclasses__()",
        "c = __builtins__",
    ],
)
def test_forbidden_code(line):
    assert code_problems(f"{line}\n{GOOD}"), line


@pytest.mark.parametrize(
    "line",
    [
        "import json",
        "import csv, io, re, math, datetime",
        "from decimal import Decimal",
        "from collections import Counter",
        "from pathlib import PureWindowsPath",
        "from engine.custom_api import CustomContext",
        "from PIL import Image",
        "from pypdf import PdfReader",
        "from fpdf import FPDF",
    ],
)
def test_allowed_code(line):
    assert code_problems(f"{line}\n{GOOD}") == []


def test_network_modules_only_when_declared():
    source = f"import urllib.request\n{GOOD}"
    assert code_problems(source)
    assert code_problems(source, CODE_MODULES | NETWORK_MODULES) == []


def test_the_spec_function_must_exist():
    missing = code_problems("def other(ctx):\n    pass\n")
    assert "calls run(ctx), but it is not defined" in missing[0]
    assert code_problems("x = (\n")[0].startswith("custom_step.py:1: syntax error")


def test_code_rules_run_on_the_job(job):
    with (job / "custom_step.py").open("a", encoding="utf-8") as fh:
        fh.write("\nimport os\n")
    report = check_job(job)
    assert "import os is not allowed" in problems(report, "code")
    assert statuses(report)["pytest"] == "skipped"


# --- Tools --------------------------------------------------------------------------------


def test_failing_job_tests_fail_the_check(job):
    path = job / "test_custom_step.py"
    path.write_text(path.read_text().replace('"Words: 23"', '"Words: 999"'))
    report = check_job(job)
    pytest_check = next(c for c in report.checks if c.name == "pytest")
    assert pytest_check.status == "failed"
    assert "Words: 999" in pytest_check.log_tail
    assert pytest_check.command.startswith("python -m pytest")


def test_smoke_test_catches_a_step_that_breaks_the_sandbox(job):
    # Passes the static rules, but PIL's save writes outside the output folder at run time.
    (job / "custom_step.py").write_text(
        "from PIL import Image\n\n\n"
        "def run(ctx):\n"
        "    Image.new('RGB', (1, 1)).save(ctx.input('text_file') + '.png')\n"
        "    return ctx.document(b'x', 'txt')\n"
    )
    (job / "test_custom_step.py").write_text("def test_nothing():\n    pass\n")
    report = check_job(job)
    smoke = next(c for c in report.checks if c.name == "smoke_test")
    assert smoke.status == "failed"
    assert "outside the output folder" in smoke.log_tail


def test_lint_problems_fail_the_check(job):
    with (job / "custom_step.py").open("a", encoding="utf-8") as fh:
        fh.write("\n\ndef unused(ctx):\n    x = 1\n")
    assert statuses(check_job(job))["ruff"] == "failed"
