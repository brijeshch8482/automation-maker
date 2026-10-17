# MakeMyEXE: Architecture & Flow

**Product name:** MakeMyEXE (planned domain: makemyexe.com). The repos keep their working names `automation-maker` and `automation-builds`.

**One line:** Users pick a ready-made automation or describe a custom one. We build a Windows EXE that runs **on their own PC, offline**, with a step-by-step screenshot guide. **We never need the user's data, only the format of the task.**

---

## 1. Core principles (non-negotiable)

1. **Format, not data.** The AI designs the tool (fields, layout, steps). Real data is typed or selected only inside the EXE on the user's PC.
2. **Offline by default.** An automation uses the internet only if its spec declares `network.required = true` with an explicit domain list; the website shows a 🌐 badge for it.
3. **Originals are never modified.** Output always goes to a new file or folder.
4. **Never delete.** Files are only moved (to a review folder), and every move or rename goes to an undo log.
5. **Preview before changing files** (rename, organize, move).
6. **No telemetry in the EXE.** No usage tracking, no auto-update calls. Errors are shown with a "Copy error report" button whose text never includes file contents or input values.
7. **Spec is the source of truth.** Every automation is one `AutomationSpec` (JSON). The web preview, EXE, tests and guide are all generated from it.
8. **Generated code never runs where secrets live.** CI jobs that execute generated code have no secrets.

---

## 2. Phases

| | **Internal phase (now)** | **Live phase (later)** |
|---|---|---|
| Who uses it | Founder + team | Public users |
| Spec design | Claude Code routine `am-spec`, async (fired from FastAPI) | Claude API, live streaming chat |
| Code generation + repair | Claude Code routine `am-build` (fired from FastAPI) | Claude Managed Agents session |
| Billing for AI | Founder's Claude subscription | Anthropic API key (pay per use) |
| Windows build | GitHub Actions `windows-latest` | Same |
| Signing | None (unsigned, internal testers only) | Code-signing certificate in the trusted build job |
| Web hosting | Cloudflare Pages, free (`makemyexe.pages.dev`) | Same, on `makemyexe.com` |
| FastAPI hosting | Render free web service, Docker (`makemyexe-api.onrender.com`), kept awake by a cron-job.org ping (§6.1). Local + Cloudflare Tunnel only for debugging callbacks | Render Starter or Cloud Run, on `api.makemyexe.com` |

The switch from internal to live replaces only the `GenerationProvider` implementation (§11). The web flow, job states, callbacks and build pipeline stay the same.

---

## 3. User flows

### Flow A: Ready-made automation (instant)
```text
Catalog -> automation page (description, 🔒/🌐 badge, preview, guide) -> Download (prebuilt EXE + Guide.pdf)
```

### Flow B: Custom automation (internal phase: async spec-first, two routine runs)
```text
1. User describes the task (web form)
      -> PII guard in browser + FastAPI: detect phone/email/PAN/Aadhaar/GSTIN/bank/card -> warn + mask
2. FastAPI fires routine am-spec  (mode=spec)              job: spec_requested
3. am-spec returns via callback: spec + assumptions + questions   job: spec_ready
4. Web shows LIVE PREVIEW of the EXE window rendered from the spec,
   plus the assumptions/questions. User either:
      a. edits fields directly in the preview and confirms, or
      b. answers the questions -> FastAPI fires am-spec again (revision)
5. User confirms -> FastAPI fires routine am-build (mode=build)     job: generating
      - blocks-only spec: routine just writes spec.json (no code)
      - custom step needed: routine writes custom_step.py + tests
      - Linux checks pass -> pushes branch claude/job-<id> -> callback
6. FastAPI dispatches the Windows build workflow                  job: building
7. Build callback:
      passed -> artifact stored -> download link                  job: ready
      failed and attempt < 2 -> FastAPI fires am-build (mode=repair) job: repairing
      failed and attempt = 2 -> clear failure + session links      job: failed
```

### Job states
`draft -> spec_requested -> spec_ready -> queued -> generating -> building -> repairing -> ready | failed | expired`

Each attempt row stores the routine `claude_code_session_id` and URL, so every job has a clickable trace of what Claude did.

**Watchdog:** a periodic task fails jobs with no callback in time (spec 15 min, generation 30 min, build 45 min) and keeps the session/run links for debugging.

---

## 4. Internal-phase architecture

```text
Browser ──> Web (React + Vite)
               │
               v
          FastAPI (ours) ───────── Supabase Auth + Postgres (users, specs, jobs, attempts)
            │   ▲      │
 1. /fire   │   │      │ 4. workflow_dispatch (ref=main, inputs: job_id, branch, attempt)
 (routine   │   │      v
  token)    │   │   GitHub Actions in automation-builds
            v   │     Job 1 "build" (NO secrets): checkout main + only jobs/<id>/ from job branch
   Claude Code  │       -> PyInstaller -> smoke test (sample_data) -> guide screenshots
   routines     │       -> upload artifact + report.json
   am-spec /    │     Job 2 "publish" (has secrets, never runs generated code):
   am-build     │       -> download artifact -> upload to R2 -> HMAC callback
   (Linux       │                                   │
   sessions)    │ 2/3. callback (per-job token)     │ 5. /internal/build-callback
                └───────────────────────────────────┘
                                                    R2 (private) -> expiring download URL
```

- **Routine sessions** run on Anthropic's cloud (Linux) under the founder's subscription. The fire endpoint returns `claude_code_session_id` immediately; results come back only through our callback.
- **There's no follow-up messaging into an existing session.** Each fire is a new session, so repair state lives in the git branch `claude/job-<id>` and in the fire payload.
- **Network:** the routines' cloud environment uses Custom network access: the default package-manager list plus our FastAPI hostname, for callbacks.
- **Limits (research preview, may change):** 30 fires/hour per routine, 100 API fires/hour per account; runs draw from subscription usage.

Exact payloads, routine prompts and callback contracts are in [`ROUTINES.md`](ROUTINES.md).

---

## 5. Repositories & trust boundaries

| Repo | Contains | Secrets | Who writes |
|---|---|---|---|
| `automation-maker` (private) | Everything: spec, engine, blocks, catalog, tools, build, api, web | Deploy/sync tokens; later signing | Us (developed with Claude Code on the web) |
| `automation-builds` (private) | `main`: synced snapshot of `engine/ spec/ tools/ build/` + `build.yml`. Job branches `claude/job-<id>` contain only `jobs/<id>/` | Job 2 only: R2 write key, callback HMAC secret | `main`: sync workflow from `automation-maker`. Job branches: the `am-build` routine |

**Why the build is safe even though the routine pushes branches:** the Windows workflow is started by `workflow_dispatch` on `main`, so the workflow file always comes from `main`. Job 1 copies **only** `jobs/<id>/` from the job branch, so a job branch can't change the engine, tools or workflow. Generated code runs only in Job 1, which has no secrets.

Engine sync: a workflow in `automation-maker` pushes `engine/ spec/ tools/ build/` to `automation-builds/main` when an engine version is tagged. Each job records the engine version it was built with.

---

## 6. Tech stack

| Part | Choice |
|---|---|
| Web | React + Vite + TypeScript, Tailwind; preview renderer reads the spec |
| API | FastAPI (Python 3.12), Pydantic models shared with the engine via `spec/` |
| Auth + DB | Supabase (Auth + Postgres); plain Postgres also works locally |
| AI (internal) | Claude Code routines with API triggers (`am-spec`, `am-build`) |
| AI (live) | Claude API (spec chat) + Claude Managed Agents (codegen/repair) |
| Windows build | GitHub Actions `windows-latest` in `automation-builds` |
| Storage | Cloudflare R2 (private), presigned expiring downloads |
| Desktop engine | Python 3.12 + PySide6 (Qt Widgets) |
| Doc/PDF/Excel libs | reportlab or fpdf2, pypdf, pikepdf, openpyxl, python-docx, Pillow |
| Packaging | PyInstaller `--onedir`, zipped (internal); Inno Setup per-user installer (live) |
| Checks | Ruff, pytest (Qt offscreen), Bandit, pip-audit, AST rules (`tools/check_job`) |
| Hosting (web) | Cloudflare Pages (static `web/dist`, auto-deploy from `main`) |
| Hosting (API) | Render web service from `api/Dockerfile` (`render.yaml` blueprint) |
| Keep-awake | cron-job.org: `GET /health` every 10 min (watchdog itself runs in-process) |

### 6.1 Free hosting for the internal phase (₹0)

| Part | Host | Free-tier facts that matter |
|---|---|---|
| Web | Cloudflare Pages | Unlimited bandwidth, never sleeps, free custom domain |
| API | Render free web service (Docker) | Sleeps after 15 min idle (30–50 s cold start); 750 instance hours/month; 500 build minutes/month; 512 MB RAM; no persistent disk |
| DB + Auth | Supabase free | Pauses after ~1 week with no DB activity; resume from the dashboard |
| Storage | Cloudflare R2 | 10 GB-month free, free egress |
| Keep-awake | cron-job.org | Free |

**Keep-awake:** cron-job.org calls `GET /health` every 10 minutes, which keeps the API awake (about 744 h/month, inside the 750 free hours, so this must be the **only** free Render web service on the account). The watchdog (§3) runs **inside the API process** every `WATCHDOG_INTERVAL_S` (default 60 s), so it only works while the service is awake. That's why the ping matters. If the service slept anyway, the watchdog catches up on the first request after waking. Don't use a GitHub Actions cron for the ping, because per-run minute rounding would use up the free Actions minutes.

**Render settings** ([`render.yaml`](../render.yaml), step-by-step setup in [DEPLOY.md](DEPLOY.md)): the image is `api/Dockerfile` (API + spec + the `automations/` catalog, non-root, no engine). Build Filters limited to `api/**`, `spec/**`, `automations/**`, `pyproject.toml`, `uv.lock`, so web-only commits don't spend build minutes. Health check path: `/health`. Pre-deploy commands need a paid plan, so the container runs the Alembic migrations (`python -m api.migrate`) before uvicorn on every start. All secrets are Render environment variables, never committed.

**Database and login:** `DATABASE_URL` is Supabase's **Session pooler** string (IPv4; the direct connection is IPv6-only on the free plan), used with asyncpg over SSL. The migrations turn on Row Level Security, because Supabase's Data API exposes public tables to the publishable key; the API connects as the table owner. Logins are verified with the project's JWKS (`{SUPABASE_URL}/auth/v1/.well-known/jwks.json`, RS256/ES256); HS256 with `SUPABASE_JWT_SECRET` remains only for legacy projects.

**URLs and CORS:** web `https://makemyexe.pages.dev`, API `https://makemyexe-api.onrender.com`. FastAPI's CORS allows only the web origin(s), from the `CORS_ORIGINS` env var. `PUBLIC_BASE_URL` must be the Render URL so routine payloads carry the right `callback_url`. The routines' cloud environment allowlists the exact API hostname.

**Exit plan:** if cold starts or Render policy become a problem, move the same Docker image to Google Cloud Run (free tier, 1–3 s cold starts, needs a billing card) or Render Starter ($7/month). Nothing outside hosting config changes.

---

## 7. The AutomationSpec

One JSON document per automation, defined as Pydantic models in `spec/` and exported to JSON Schema for the routines, the frontend and validation.

```json
{
  "id": "invoice-generator",
  "version": "1.0.0",
  "title": "Invoice Generator",
  "category": "documents",
  "network": { "required": false, "domains": [] },
  "settings": [
    { "key": "business_name", "type": "text", "label": "Business name", "required": true },
    { "key": "gstin", "type": "text", "label": "GSTIN" },
    { "key": "logo", "type": "image_file", "label": "Logo" },
    { "key": "output_folder", "type": "folder", "label": "Save invoices to" }
  ],
  "inputs": [
    { "key": "customer_name", "type": "text", "label": "Customer name", "required": true },
    { "key": "customer_phone", "type": "phone", "label": "Phone" },
    { "key": "items", "type": "table", "label": "Items", "columns": [
      { "key": "description", "type": "text" },
      { "key": "qty", "type": "number" },
      { "key": "rate", "type": "money" }
    ]},
    { "key": "tax_percent", "type": "number", "label": "GST %", "default": 18 }
  ],
  "steps": [
    { "block": "counter.next", "args": { "name": "invoice_no", "prefix": "INV-" }, "out": "invoice_no" },
    { "block": "calc.line_totals", "args": { "table": "items", "qty": "qty", "rate": "rate", "tax": "tax_percent" }, "out": "totals" },
    { "block": "pdf.render_template", "args": { "template": "invoice_basic" }, "out": "pdf" },
    { "block": "file.save", "args": { "source": "pdf", "folder": "@settings.output_folder", "name": "{invoice_no}.pdf" } }
  ],
  "output": { "type": "file", "open_after": true },
  "sample_data": { "customer_name": "Asha Traders", "items": [{ "description": "Sample item", "qty": 2, "rate": 500 }] }
}
```

- `settings`: entered once, saved locally in `%APPDATA%\MakeMyEXE\<id>\settings.json`.
- `inputs`: filled each run.
- `steps`: a pipeline of library blocks. A custom step is `{ "block": "custom.step", "args": { "function": "run" } }`.
- `sample_data`: **fake** data for smoke tests and guide screenshots.

---

## 8. Desktop engine (inside every EXE)

```text
EXE = Engine (same for all, fully tested) + spec.json + templates/assets + optional custom_step.py
```

- **Standard UI shell:** header -> first-time setup (settings) -> inputs form -> preview (if files change) -> Run -> result (open file/folder, undo).
- **Block library v1:** `form.*`, `settings.*`, `counter.*`, `calc.*`, `pdf.render_template`, `pdf.merge/split/compress/watermark/encrypt`, `image.*`, `excel.read/write/combine/dedupe/compare/split/summary`, `convert.*`, `files.scan/rename/organize/find_duplicates`, `file.save`, `undo.*`.
- **Custom-step context API** (`engine/custom_api.py`): read user-selected inputs, write only to the output folder, move only through the undo log; no delete, no subprocess, no network unless declared.
- **Custom-step sandbox** (`engine/sandbox.py`): while generated code runs (module level included), a Python audit hook refuses writes outside the output folder, deletes, renames, starting programs, native libraries and (unless declared) network connections. It backs up the static rules in `tools.check_job`.
- **Offline guard:** with `network.required = false`, sockets are blocked at startup, network libraries aren't bundled, and generated code importing `socket/urllib/requests/http*` fails the checks.
- **Guide mode:** `app.exe --guide-mode out/` renders every screen with `sample_data`, saves screenshots, and the build produces `Guide.pdf` + HTML.
- **Local data:** settings JSON + SQLite (counters, saved customers) in `%APPDATA%`, never sent anywhere.

---

## 9. Build & validation gates

1. **Spec validation** (`tools.validate_spec`): schema, known blocks, allowed category, network rules. Run by `am-spec` before callback and by FastAPI on receipt.
2. **Job checks on Linux** (`tools.check_job`, run inside the `am-build` session): folder layout, spec + sample files, AST rules (allowlisted imports, no dynamic code or dunder access), Ruff, Bandit, pytest with `sample_data`, the engine's smoke test.
3. **Windows Job 1 (no secrets), pinned** to the commit that passed those checks and to the fingerprint of the spec the user confirmed (a later push or a changed spec fails at `validate`): PyInstaller build -> smoke test -> guide screenshots -> artifact + `report.json` (stage, command, test, bounded log).
4. **Windows Job 2 (secrets, no generated code):** upload to R2 -> HMAC-signed callback.
5. **Repair:** FastAPI fires `am-build` in `repair` mode with the report; max 2 repairs.
6. **Only passing builds are downloadable.** Links expire.

---

## 10. API (FastAPI)

| Method | Path | Purpose |
|---|---|---|
| GET | `/automations` | Catalog list |
| GET | `/automations/{id}` | Details, badge, guide |
| POST | `/automations/{id}/download` | Expiring download URL |
| POST | `/jobs` | New custom job from a description -> fires `am-spec` -> `202 {job_id}` |
| GET | `/jobs/{id}` | Status, spec, assumptions, questions, attempts (with session links), download |
| POST | `/jobs/{id}/answers` | Answer questions -> spec revision (fires `am-spec`) |
| PUT | `/jobs/{id}/spec` | Save the user-edited spec (validated) |
| POST | `/jobs/{id}/confirm` | Confirm spec -> fires `am-build` |
| GET | `/me/jobs` | The user's custom automations |
| POST | `/internal/routine-callback` | From routines; per-job bearer token |
| POST | `/internal/build-callback` | From GitHub Actions Job 2; HMAC signature |
| GET | `/health` | Render health check + cron-job.org keep-awake ping; no DB call |

Access: catalog browsing and downloads need no login; custom jobs need a login. Raw descriptions are deleted after 30 days; specs are kept.

---

## 11. GenerationProvider (the swap point)

```python
class GenerationProvider(Protocol):
    async def request_spec(self, job: Job, description: str, answers: list[Answer] | None) -> RunRef: ...
    async def request_build(self, job: Job, spec: AutomationSpec) -> RunRef: ...
    async def request_repair(self, job: Job, report: BuildReport) -> RunRef: ...
```

- `RoutineProvider` (internal): POSTs to the routine `/fire` endpoints, returns `RunRef(session_id, session_url)`. Results arrive at `/internal/routine-callback`.
- `ClaudeApiProvider` (live): spec via Claude API (streamed chat in the UI), build/repair via Managed Agents. It produces the same `spec_ready` / `generation_done` events, so `JobService` and everything downstream stays unchanged.

Both providers end up calling the same handlers: `JobService.on_spec_ready(...)` and `JobService.on_generation_done(...)`.

---

## 12. Repository layout (`automation-maker`)

```text
automation-maker/
  CLAUDE.md
  docs/ARCHITECTURE.md
  docs/ROUTINES.md      routine prompts, payloads, callback contracts, cloud environment setup
  docs/SPEC_GUIDE.md    how to design specs; read by am-spec
  spec/                 Pydantic AutomationSpec models + JSON Schema export + block catalog
  engine/               PySide6 shell, block library, custom_api, runtime guards, guide mode
  tools/                validate_spec, check_job (lint/test/AST rules)
  automations/          ready-made catalog: one folder per automation (spec.json, templates, tests)
  build/                PyInstaller spec, guide PDF generator, local build script
  api/                  FastAPI app (JobService, GenerationProvider, callbacks)
  web/                  React + Vite frontend
  builds-repo/          source for automation-builds main: .github/workflows/build.yml, README
  .github/workflows/
    ci.yml              lint + tests
    sync-builds.yml     pushes engine/spec/tools/build + builds-repo/ to automation-builds main
    build-catalog.yml   builds ready-made automations
```

---

## 13. Development phases

| Phase | Goal | Done when |
|---|---|---|
| 0 | Repo, CLAUDE.md, CI skeleton | CI runs Ruff + pytest |
| 1 | **Spec models + engine + 3 automations** (Invoice, PDF Merge, Bulk Rename) | They run on Windows from `spec.json` |
| 2 | Windows packaging + guide mode; `automation-builds` repo + `build.yml` | A manual dispatch produces a zip + Guide.pdf |
| 3 | FastAPI jobs + callbacks + `RoutineProvider`; routines `am-spec` and `am-build` set up | Description -> spec -> EXE end-to-end, triggered from curl |
| 4 | Web: catalog, job flow with spec preview/edit, downloads | Full Flow B in the browser |
| 5 | Rest of Wave 1 catalog + repair loop hardening + watchdog | 9 automations; failing jobs repair or fail cleanly |
| 6 | Live phase: `ClaudeApiProvider`, signing, hosting, rate limits | Public beta |

---

## 14. Open decisions

- Pricing: free catalog + paid custom builds, or a subscription.
- Buy makemyexe.com (name decided: MakeMyEXE).
- Code-signing route (country/business registration).
- Live-phase API host: Render Starter vs Cloud Run (internal phase is decided: §6.1).
- Later: online automations (🌐) with a domain allowlist; macOS.
