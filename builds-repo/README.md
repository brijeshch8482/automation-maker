# automation-builds

Build sandbox for MakeMyEXE custom jobs. Do not develop here: everything on `main` is synced from `automation-maker` and overwritten on the next sync.

- `main` is a snapshot of `engine/ spec/ tools/ build/`, the uv workspace files and `.github/workflows/build.yml` from `automation-maker` (`builds-repo/` there). Only the sync workflow writes to it; `ENGINE_VERSION` names the tag and commit.
- `claude/job-<id>` branches are written by the `am-build` routine and contain only `jobs/<id>/`.
- `build.yml` is started by the API with `workflow_dispatch` on `main`. Job 1 (`windows-latest`, no secrets) takes only `jobs/<id>/` from the job branch, packages it with `python -m build.package`, runs the smoke test, a launch check and the guide, and uploads the zip, `Guide.pdf` and `report.json`. Job 2 (no generated code) uploads a passing build to R2 and sends the signed callback.

Settings (Settings › Secrets and variables › Actions), all from `docs/DEPLOY.md` in `automation-maker`:

| Name | Kind |
|---|---|
| `API_BASE_URL` | variable |
| `BUILD_CALLBACK_SECRET` | secret, the same value as in the API |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` | secrets |

Until they are set, a build only checks the job and keeps the result as a GitHub artifact.
