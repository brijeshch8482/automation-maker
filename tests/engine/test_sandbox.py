"""engine.sandbox: what a running custom step may and may not do."""

import os
import subprocess
import sys
import threading

import pytest

from engine.sandbox import SandboxError, confined


def test_writes_only_inside_the_output_folder(tmp_path):
    out, elsewhere = tmp_path / "out", tmp_path / "elsewhere.txt"
    with confined(out):
        (out / "report.txt").write_text("ok")
        (out / "sub").mkdir()
        with pytest.raises(SandboxError):
            elsewhere.write_text("no")
        with pytest.raises(SandboxError):
            os.open(elsewhere, os.O_WRONLY | os.O_CREAT)
        with pytest.raises(SandboxError):
            (tmp_path / "new-folder").mkdir()
    assert (out / "report.txt").read_text() == "ok"
    assert not elsewhere.exists()
    elsewhere.write_text("fine once the step is done")


def test_reading_stays_allowed(tmp_path):
    source = tmp_path / "input.txt"
    source.write_text("hello")
    with confined(tmp_path / "out"):
        assert source.read_text() == "hello"


def test_no_deleting_renaming_or_programs(tmp_path):
    out = tmp_path / "out"
    victim = tmp_path / "keep.txt"
    victim.write_text("keep")
    with confined(out):
        for action in (
            lambda: os.remove(victim),
            lambda: os.rename(victim, out / "moved.txt"),
            lambda: os.replace(victim, out / "moved.txt"),
            lambda: os.chmod(victim, 0o777),
            lambda: subprocess.run([sys.executable, "-c", "pass"], check=False),
            lambda: os.system("echo hi"),
        ):
            with pytest.raises(SandboxError):
                action()
        # Even the step's own output may not be deleted (never delete user files).
        (out / "mine.txt").write_text("x")
        with pytest.raises(SandboxError):
            os.remove(out / "mine.txt")
    assert victim.read_text() == "keep"


def test_network_only_when_the_spec_declares_it(tmp_path):
    import socket

    with confined(tmp_path), pytest.raises(SandboxError):
        socket.getaddrinfo("localhost", 80)
    with confined(tmp_path, network=True):
        socket.getaddrinfo("localhost", 80)


def test_threads_are_confined_too(tmp_path):
    errors = []

    def write():
        try:
            (tmp_path / "from-thread.txt").write_text("no")
        except SandboxError as err:
            errors.append(err)

    with confined(tmp_path / "out"):
        thread = threading.Thread(target=write)
        thread.start()
        thread.join()
    assert errors and not (tmp_path / "from-thread.txt").exists()


def test_sandbox_error_is_a_permission_error_without_user_values(tmp_path):
    with confined(tmp_path / "out"), pytest.raises(PermissionError) as info:
        (tmp_path / "secret-name.txt").write_text("x")
    assert "secret-name" not in str(info.value)
