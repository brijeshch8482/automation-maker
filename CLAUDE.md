# MakeMyEXE

Web product where users pick a ready-made automation or describe a custom one, and we build a Windows EXE that runs offline on their own PC, with a screenshot guide. Delivery is moving to one shared Runner + signed app packs merged at download (`docs/ARCHITECTURE.md` §8, Phases 2b/2c); until 2b ships, the per-automation PyInstaller pipeline stays live. Read `docs/ARCHITECTURE.md` before starting any phase; read `docs/ROUTINES.md` before touching generation, callbacks or the build workflow.

## Rules that must never be broken
- **Format, not data:** the AI and server never need user data; real data is entered only inside the EXE.
- **Offline by default:** no network code in an automation unless its spec declares `network.required = true` with domains.
- **Never modify originals, never delete user files.** Write to new files/folders; moves and renames go through the undo log.
- **No telemetry or auto-update calls in the EXE.**
- **Only signed packs run; nothing is downloaded or installed on the user's PC at runtime.** The Runner verifies the pack signature and every pack and layer hash before loading anything (`docs/ARCHITECTURE.md` §8.3). Signing keys live only in the `catalog` / `publish` environments.
- **Custom code imports only the stdlib, `engine.custom_api`, the Runner lock and the job's resolved layers.** New libraries go through the policy gate (§8.5), never around it; a policy reject never falls back to the standalone build.
- **AutomationSpec is the source of truth** (`spec/`). Change the models there first, then regenerate JSON Schema and TS types.
- **Generated code never runs in a CI job that has secrets.** The Windows workflow is dispatched on `main` and copies only `jobs/<id>/` from job branches.
- **Secrets only in GitHub environments limited to `main`** (`catalog`, `sync`, and `publish` in automation-builds), never repository secrets; the job that runs generated code gets no secrets and no cache (`tests/packaging/test_workflow_secrets.py`, `docs/ROUTINES.md` §5).
- **All AI generation goes through `GenerationProvider`** (`api/`). Internal phase: `RoutineProvider` (Claude Code routines). Live phase: `ClaudeApiProvider`. Nothing outside the provider may depend on which one is active.

## Layout
`spec/` models + block catalog · `engine/` desktop runtime (PySide6) · `tools/` validate_spec, check_job · `automations/` catalog · `build/` packaging + guide · `api/` FastAPI · `web/` React · `builds-repo/` source for the `automation-builds` repo.

## Verification (every PR)
- Run the full test suite headless (`QT_QPA_PLATFORM=offscreen`) before opening a PR.
- **Any UI change must ship screenshots.** Render each affected screen offscreen with the automation's `sample_data` (the same code path as guide mode, `QWidget.grab()`), save the PNGs under `docs/screenshots/<automation-id>/`, **open and look at them yourself** to check layout, labels, clipping and empty states, then embed them in the PR description.
- For non-UI work, include in the PR description: the commands run, the test results, and sample output (e.g. the generated PDF rendered to PNG, or the rename preview table).
- CI runs on both `ubuntu-latest` and `windows-latest`. The Windows job also renders the screenshots and uploads them as an artifact, so Windows rendering gets checked on every PR.

## Development notes
- EXEs target Windows 10/11. Cloud dev is Linux: run Qt tests with `QT_QPA_PLATFORM=offscreen`; real Windows builds run in GitHub Actions.
- Python 3.12, Ruff for lint/format, pytest for tests. Every block and every catalog automation needs tests that use its `sample_data`.
- Routine prompts in `docs/ROUTINES.md` must match what's saved at claude.ai/code/routines. Update both together.

## Commands
uv workspace (root `pyproject.toml`, members `spec/`, `engine/` and `api/`; `tools/` is imported from the repo root). Run everything from the repo root.
- Install: `uv sync`
- Lint / format: `uv run ruff check .` · `uv run ruff format .` (CI uses `--check`)
- Tests: `QT_QPA_PLATFORM=offscreen uv run pytest`
- Validate a spec: `uv run python -m tools.validate_spec <file> [<file> ...]` (exit 1 on any issue)
- Check a generated job folder like the `am-build` routine does: `uv run python -m tools.check_job jobs/<id> [--json]` (layout, spec, code rules, ruff, bandit, its pytest, smoke test; exit 1 on failure). Tests run it on every catalog automation and on `tests/fixtures/jobs/word-count/` (a job with a custom step, synced to automation-builds as `examples/custom/word-count/`).
- Custom steps (`custom.step` → `custom_step.py`): only the context API (`engine/custom_api.py`; output via `ctx.document(...)` + `file.save`), only `tools.check_job`'s allowlisted imports, and `engine/sandbox.py` confines them at run time (writes only into the output folder; no delete, rename, programs or network). Their tests use `engine.testing.run_custom_step`. Spec design guide for routines: `docs/SPEC_GUIDE.md`.
- Custom builds are pinned: the API dispatches `build.yml` with the routine's `commit` and the confirmed spec's fingerprint (`python -m spec.fingerprint spec.json`, `build.package --expect-spec-sha256`).
- Regenerate JSON Schema + block catalog after changing `spec/`: `uv run python -m spec.export_schema` (writes `spec/schema/`; `--check` fails if stale, CI runs it)
- Engine (`engine/`): run an automation `uv run python -m engine automations/<id>/spec.json`; headless check on `sample_data` `... --smoke-test` (JSON report, exit 1 on failure); guide screenshots `... --guide-mode docs/screenshots/<id>/` (renders every screen offscreen with `QWidget.grab()`, plus `manifest.json` and the sample output). Local data goes to `%APPDATA%\MakeMyEXE\<id>\` (override with `MAKEMYEXE_DATA_DIR`). Linux needs Qt libs and fonts: `apt-get install libegl1 libxkbcommon0 libfontconfig1 libdbus-1-3 fonts-dejavu-core fonts-lohit-deva`.
- Catalog automations with file/folder inputs ship tiny, obviously fake sample files in `automations/<id>/samples/`; `sample_data` paths are relative to `spec.json`. Smoke tests and guide mode copy them to a temp folder first, so a run never renames or changes them.
- Blocks that change user files (e.g. `files.rename`) only return a plan; the engine shows a preview, applies it through `engine/changes.py` (undo log first, two-phase moves, never overwrite or delete) and offers Undo. List any such block in `FILE_CHANGING_BLOCKS` in `web/src/lib/fields.ts` so the website describes it honestly.
- Add a block implementation: catalog entry in `spec/` first, then a function in `engine/src/engine/blocks/` registered in `blocks/__init__.py`, with tests on `sample_data`. Errors raised as `EngineError` must not contain user values (they appear in the error report).
- Package an automation like the Windows build does (`build/`): `uv sync --group build`, then `uv run python -m build.package automations/<id> --out dist/ [--launch-check]` → `dist/<ExeName>.zip`, `Guide.pdf`, `report.json` (stages validate, package, smoke_test, launch_check, guide, guide_pdf, zip; on failure the stage, command and log tail the repair routine reads). PyInstaller `--onedir`, Qt trimmed; blocks load lazily, so each EXE bundles only its blocks' libraries (new block modules go in `IMPLEMENTATIONS` as `"module:function"`). CI packages every catalog automation on Windows (artifacts `app-<id>`); add new ones to the `package` matrix in `ci.yml`. Job `package (custom step)` packages the word-count fixture the way automation-builds does (artifact `job-word-count`, never published).
- automation-builds: its `main` is synced from here by `.github/workflows/sync-builds.yml` (`builds-repo/sync.py`; tag `engine-v*` or run by hand). Edit `build.yml`, the README and its `CLAUDE.md` (what the routines read there) in `builds-repo/`, never in that repo; `sync.py` also copies `docs/SPEC_GUIDE.md` and the examples. `build/publish.py` (its Job 2) is standard library only and treats the artifact as untrusted.
- Downloads (`api/storage.py`): apps in a private R2 bucket; the API signs 15-minute GET links (SigV4, stdlib, no AWS SDK) with a **read-only** token. Catalog: CI job `publish catalog` (push to `main` only, after `test` + `package`) runs `build/publish_catalog.py`, uploading `catalog/<id>/<version>/` and then `catalog/manifest.json`, which `GET /automations/{id}/download` reads (cached 5 min). Custom apps: links on `GET /jobs/{id}` once ready. Website: `components/DownloadCard.tsx`.
- API (`api/`): `uv run uvicorn api.app:create_app --factory --reload` (settings from env or `.env`, see `.env.example`; defaults: SQLite, fake provider, no login). With `DEV_AUTH=true`, call it with `Authorization: Bearer dev:<user>`; play a routine by POSTing to `/internal/routine-callback` with the job's token (`api.security.callback_token`).
- Database migrations: `uv run python -m api.migrate` (upgrade to head; the container runs it on start). New migration after changing `api/src/api/db.py`: `uv run alembic -c api/alembic.ini revision --autogenerate -m "..."`, then review it and replace any `api.*` imports with plain SQLAlchemy types.
- API image: `docker build -f api/Dockerfile -t makemyexe-api .` then `docker run -p 8000:8000 -e DATABASE_URL=sqlite+aiosqlite:////tmp/dev.db makemyexe-api`. Deployment (Render, Supabase, Cloudflare Pages): `docs/DEPLOY.md`. Secrets go only into those dashboards, never into the repo or a chat.
- Web (`web/`, Node 22): `npm ci` · `npm run dev` · `npm test` · `npm run typecheck` · `npm run build`
- TS types from the spec schema (after `spec.export_schema`): `npm run gen:types` in `web/` (`check:types` in CI)
- Web against the local API: run the API (above) with `DEV_AUTH=true`, then in `web/` copy `.env.example` to `.env.local` and `npm run dev`.
- Website pages: home `/`, catalog `/automations` (search + category filter), detail, custom-app flow, `/privacy`, `/terms`. The ready-made catalog is bundled from `automations/*/spec.json`, so it never waits for the API; keep the Privacy page true to what `api/` stores (retention in `api/src/api/config.py`). Optional `VITE_CONTACT_EMAIL` shows a contact address. Share image and touch icon: `node scripts/brand-images.mjs` in `web/` (from `public/favicon.svg`).
- Web screenshots: `npm run screenshots` in `web/` → `docs/screenshots/web/`. Builds the site itself, then starts the real API (fake provider, dev login) and walks the whole custom-job flow, playing the routine/build callbacks. Needs `uv` and Chromium (`/opt/pw-browsers/chromium`, or set `CHROMIUM_PATH`).
- Add a block: define its args model and `BlockDef` in `spec/src/spec/catalog.py`, mark spec references with `ValueRef` / `InputRef(...)` / `ColumnRef(...)` / `TemplateStr`, then regenerate the schema.
