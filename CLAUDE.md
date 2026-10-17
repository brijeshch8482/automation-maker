# MakeMyEXE

Web product where users pick a ready-made automation or describe a custom one, and we build a Windows EXE that runs offline on their own PC, with a screenshot guide. Read `docs/ARCHITECTURE.md` before starting any phase; read `docs/ROUTINES.md` before touching generation, callbacks or the build workflow.

## Rules that must never be broken
- **Format, not data:** the AI and server never need user data; real data is entered only inside the EXE.
- **Offline by default:** no network code in an automation unless its spec declares `network.required = true` with domains.
- **Never modify originals, never delete user files.** Write to new files/folders; moves and renames go through the undo log.
- **No telemetry or auto-update calls in the EXE.**
- **AutomationSpec is the source of truth** (`spec/`). Change the models there first, then regenerate JSON Schema and TS types.
- **Generated code never runs in a CI job that has secrets.** The Windows workflow is dispatched on `main` and copies only `jobs/<id>/` from job branches.
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
- Commands: add them here as each package is set up.
