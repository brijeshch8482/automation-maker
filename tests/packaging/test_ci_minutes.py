"""CI stays inside GitHub Free's 2,000 minutes (Windows minutes count twice): a pull request runs
only Linux jobs, docs-only changes run nothing, and main runs everything publish catalog needs.
Windows builds and tests run on the developer's PC before a PR (CLAUDE.md, local-first)."""

import yaml

from tests.conftest import REPO_ROOT

CI = yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
WINDOWS_JOBS = {
    name for name, job in CI["jobs"].items() if "windows" in str(job.get("runs-on", "")).lower()
}


def test_docs_only_changes_run_nothing():
    for event in ("push", "pull_request"):
        assert set(CI[True][event]["paths-ignore"]) == {"docs/**", "**/*.md"}  # `on` reads as True


def test_pull_requests_skip_every_windows_job():
    assert {"package", "runner", "package-custom"} == WINDOWS_JOBS
    for name in WINDOWS_JOBS:
        assert CI["jobs"][name]["if"] == "github.event_name == 'push'", name
    matrix = CI["jobs"]["test"]["strategy"]["matrix"]["os"]
    assert "github.event_name == 'push'" in matrix and "windows-latest" in matrix
    assert matrix.rstrip("}) ").endswith("'[\"ubuntu-latest\"]'")  # a PR gets Linux only


def test_main_publishes_with_the_windows_builds():
    publish = CI["jobs"]["publish-catalog"]
    assert set(publish["needs"]) == {"test", "package", "runner"}
    assert "refs/heads/main" in publish["if"]


def test_a_newer_pr_push_cancels_the_older_run_but_main_never_does():
    assert CI["concurrency"]["cancel-in-progress"] == "${{ github.event_name == 'pull_request' }}"
