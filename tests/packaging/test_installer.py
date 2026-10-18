"""The installer (installer/MakeMyEXE.iss, build/installer.py, .github/workflows/release.yml).

Building and installing need Windows: the release workflow does that on windows-latest
(`build.installer check`). These tests pin what must stay true of the script and the workflow.
"""

import json
import re
import shutil
import subprocess
import sys

import pytest
import yaml

from build import installer
from build import pack as build_pack
from engine.pack import verify_pack
from tests.conftest import AUTOMATIONS_DIR, REPO_ROOT

ISS = (REPO_ROOT / "installer" / "MakeMyEXE.iss").read_text(encoding="utf-8")
RELEASE = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "release.yml").read_text())


def section(name: str) -> list[str]:
    match = re.search(rf"^\[{name}\]\n(.*?)(?=^\[|\Z)", ISS, re.M | re.S)
    assert match, name
    return [line for line in match.group(1).splitlines() if line and not line.startswith(";")]


def test_per_user_without_admin():
    setup = section("Setup")
    assert "PrivilegesRequired=lowest" in setup
    assert "PrivilegesRequiredOverridesAllowed=" in setup  # never offers "all users"
    assert "DefaultDirName={userpf}\\MakeMyEXE" in setup
    assert f"AppId={{{installer.APP_ID}" in setup


def test_registry_is_hkcu_only_and_registers_mmx():
    lines = section("Registry")
    assert lines and all(line.startswith("Root: HKCU;") for line in lines)
    assert "HKLM" not in ISS and "HKA" not in ISS
    command = next(line for line in lines if "shell\\open\\command" in line)
    assert '"""{app}\\MakeMyEXE.exe"" --import ""%1"""' in command
    assert any('Subkey: "Software\\Classes\\.mmx"' in line for line in lines)


def test_uninstall_keeps_user_files_and_asks_about_the_store():
    deletes = section("UninstallDelete")
    assert deletes == ['Type: filesandordirs; Name: "{userprograms}\\MakeMyEXE"']
    code = ISS[ISS.index("[Code]") :]
    # Keep is the default answer, also in a silent uninstall.
    assert "MB_YESNO or MB_DEFBUTTON2, IDNO) = IDYES" in code
    removed = re.findall(r"DelTree\(ExpandConstant\('([^']+)'\)", code)
    assert removed == ["{localappdata}\\MakeMyEXE", "{userappdata}\\MakeMyEXE"]


def test_upgrade_keeps_the_store():
    # The store is outside {app}; only the app's own subfolders are replaced on upgrade.
    assert section("InstallDelete") == [
        'Type: filesandordirs; Name: "{app}\\preinstalled"',
        'Type: filesandordirs; Name: "{app}\\_internal"',
    ]


def test_release_workflow_keeps_secrets_away_from_the_windows_build():
    jobs = RELEASE["jobs"]
    build = jobs["installer"]
    assert "environment" not in build and "secrets." not in json.dumps(build)
    for name in ("catalog-packs", "publish"):
        assert jobs[name]["environment"] == "catalog"
        assert "refs/heads/main" in jobs[name]["if"]
        assert "workflow_dispatch" in jobs[name]["if"]
    assert "secrets." not in json.dumps(jobs["test-packs"])
    # test-packs is skipped on main, so publish must not rely on the implicit success(),
    # which checks every upstream job: it would be skipped too, and nothing would upload.
    assert "!cancelled()" in jobs["publish"]["if"]
    assert "needs.installer.result == 'success'" in jobs["publish"]["if"]
    triggers = RELEASE[True]
    assert set(triggers) == {"workflow_dispatch", "pull_request"}  # never on a push or a tag


def test_installer_module_is_standard_library_only():
    # The signing and publish jobs run plain python3, without the project's packages.
    subprocess.run(
        [sys.executable, "-S", "-c", "import build.installer"], cwd=REPO_ROOT, check=True
    )


@pytest.mark.skipif(shutil.which("openssl") is None, reason="needs the openssl CLI")
def test_free_set_is_signed_and_the_key_must_be_trusted(tmp_path):
    private, public = build_pack.keygen("free-1", tmp_path / "keys")
    pem = private.read_text()
    made = installer.sign_packs(AUTOMATIONS_DIR, tmp_path / "out", pem, "free-1", None, "1.0.0")
    assert sorted(p.name for p in made) == sorted(
        f"{p.name}.mmx" for p in AUTOMATIONS_DIR.iterdir() if (p / "spec.json").is_file()
    )
    for pack in made:
        assert verify_pack(pack, {"free-1": bytes.fromhex(public)}).manifest["kind"] == "catalog"

    trusted = tmp_path / "trusted.json"
    trusted.write_text(json.dumps({"free-1": "00" * 32}))
    with pytest.raises(installer.KeyNotTrusted, match=public):
        installer.sign_packs(AUTOMATIONS_DIR, tmp_path / "x", pem, "free-1", trusted, "1.0.0")
    trusted.write_text(json.dumps({"free-1": public}))
    assert installer.sign_packs(AUTOMATIONS_DIR, tmp_path / "y", pem, "free-1", trusted, "1.0.0")


def test_publish_uploads_the_installer_then_the_pointer(tmp_path, monkeypatch):
    setup = tmp_path / "MakeMyEXE-Setup-1.2.3.exe"
    setup.write_bytes(b"MZ installer")
    uploads = []

    def fake_upload(path, key, env, content_type=None):
        uploads.append((key, path.read_bytes()))

    monkeypatch.setattr(installer, "upload", fake_upload)
    env = dict.fromkeys(installer.R2_SETTINGS, "x")
    latest = installer.publish_installer(setup, env)
    assert [key for key, _ in uploads] == ["app/1.2.3/MakeMyEXE-Setup-1.2.3.exe", "app/latest.json"]
    assert json.loads(uploads[1][1]) == latest
    assert latest["version"] == "1.2.3" and latest["size_bytes"] == len(b"MZ installer")
    with pytest.raises(installer.PublishError, match="missing"):
        installer.publish_installer(setup, {})
    with pytest.raises(installer.PublishError, match="unexpected installer name"):
        installer.publish_installer(tmp_path / "setup.exe", env)


@pytest.mark.skipif(sys.platform == "win32", reason="the guard is for development machines")
def test_check_refuses_to_install_on_a_development_machine(monkeypatch, tmp_path):
    monkeypatch.delenv("CI", raising=False)
    with pytest.raises(SystemExit):
        installer.main(["check", str(tmp_path / "x.exe"), "--expect", "a", "--out", str(tmp_path)])
