# MakeMyEXE: Architecture & Flow

**Product name:** MakeMyEXE (planned domain: makemyexe.com). The repos keep their working names `automation-maker` and `automation-builds`.

**One line:** Users pick a ready-made automation or describe a custom one. We deliver a Windows app (one EXE in a zip, no install) that runs **on their own PC, offline**, with a step-by-step screenshot guide. **We never need the user's data, only the format of the task.**

---

## 1. Core principles (non-negotiable)

1. **Format, not data.** The AI designs the tool (fields, layout, steps). Real data is typed or selected only inside the EXE on the user's PC.
2. **Offline by default.** An automation uses the internet only if its spec declares `network.required = true` with an explicit domain list; the website shows a 🌐 badge for it.
3. **Originals are never modified.** Output always goes to a new file or folder.
4. **Never delete.** Files are only moved (to a review folder), and every move or rename goes to an undo log.
5. **Preview before changing files** (rename, organize, move).
6. **No telemetry in the EXE.** No usage tracking, no auto-update calls, no downloading code at runtime. Errors are shown with a "Copy error report" button whose text never includes file contents or input values.
7. **Spec is the source of truth.** Every automation is one `AutomationSpec` (JSON). The web preview, EXE, tests and guide are all generated from it.
8. **Generated code never runs where secrets live.** CI jobs that execute generated code (or third-party library code) have no secrets.
9. **Only signed packs run.** The Runner refuses an app whose signature or file hashes don't match (§8.3). Signing keys live only in publish jobs that never run generated code.

---

## 2. Phases

| | **Internal phase (now)** | **Live phase (later)** |
|---|---|---|
| Who uses it | Founder + team | Public users |
| Spec design | Claude Code routine `am-spec`, async (fired from FastAPI) | Claude API, live streaming chat |
| Code generation + repair | Claude Code routine `am-build` (fired from FastAPI) | Claude Managed Agents session |
| Billing for AI | Founder's Claude subscription | Anthropic API key (pay per use) |
| App builds | Linux pack builds on GitHub Actions `ubuntu-latest` (§8, §9) | Same |
| Windows builds | `windows-latest` only for Runner releases, native library checks and the standalone fallback | Same |
| Signing | Packs: Ed25519 (§8.3). Runner: unsigned (internal testers only) | Packs: same. Runner: code-signing certificate in the release job |
| Downloads | Cloudflare Worker merges Runner + layers + pack (§8.6) | Same |
| Web hosting | Cloudflare Pages, free (`makemyexe.pages.dev`) | Same, on `makemyexe.com` |
| FastAPI hosting | Render free web service, Docker (`makemyexe-api.onrender.com`), kept awake by a cron-job.org ping (§6.1). Local + Cloudflare Tunnel only for debugging callbacks | Render Starter or Cloud Run, on `api.makemyexe.com` |

The switch from internal to live replaces only the `GenerationProvider` implementation (§11). The web flow, job states, callbacks and build pipeline stay the same.

---

## 3. User flows

### Flow A: Ready-made automation (instant)
```text
Catalog -> automation page (description, 🔒/🌐 badge, preview, guide)
        -> Download: the Worker merges Runner + layers + signed catalog pack into <App>.zip (+ Guide.pdf)
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
      - custom step needed: routine writes custom_step.py + tests,
        and requirements.txt if it imports a third-party library
      - Linux checks pass -> pushes branch claude/job-<id> -> callback (with `requires`)
6. FastAPI resolves libraries (§8.4) against the Runner lock + layer index:
      all layers exist        -> continue
      new library             -> layer.yml builds it through the policy gate (§8.5), then continue
      library rejected        -> repair fire "rewrite without it"; still needed -> needs_library
7. FastAPI dispatches the pack build (Linux)                       job: building
8. Build callback:
      passed -> signed pack stored -> Download                     job: ready
      failed and attempt < 2 -> FastAPI fires am-build (mode=repair) job: repairing
      failed and attempt = 2 -> clear failure + session links      job: failed
```

### Job states
`draft -> spec_requested -> spec_ready -> queued -> generating -> building -> repairing -> ready | failed | expired`, plus `needs_library` (waiting for a human decision on a library, §8.5).

Each attempt row stores the routine `claude_code_session_id` and URL, so every job has a clickable trace of what Claude did.

**Watchdog:** a periodic task fails jobs with no callback in time (spec 15 min, generation 30 min, build 45 min) and keeps the session/run links for debugging.

---

## 4. Internal-phase architecture

```text
Browser ──> Web (React + Vite)
               │                                   Download ──> Cloudflare Worker (token from API)
               v                                                 merges Runner + layers + pack from R2
          FastAPI (ours) ───────── Supabase Auth + Postgres (users, specs, jobs, attempts, layers)
            │   ▲      │
 1. /fire   │   │      │ 4. workflow_dispatch (ref=main, inputs: job_id, branch, attempt)
 (routine   │   │      v
  token)    │   │   GitHub Actions in automation-builds
            v   │     Job 1 "build" (NO secrets, ubuntu): checkout main + only jobs/<id>/ from job branch
   Claude Code  │       -> check_job -> smoke test (sample_data) -> guide screenshots -> pack files
   routines     │       -> upload artifact + report.json
   am-spec /    │     Job 2 "publish" (has secrets, never runs generated code):
   am-build     │       -> download artifact -> sign pack -> upload to R2 -> HMAC callback
   (Linux       │                                   │
   sessions)    │ 2/3. callback (per-job token)     │ 5. /internal/build-callback
                └───────────────────────────────────┘
                                                    R2 (private): runner, layers, packs
```

- **Routine sessions** run on Anthropic's cloud (Linux) under the founder's subscription. The fire endpoint returns `claude_code_session_id` immediately; results come back only through our callback.
- **There's no follow-up messaging into an existing session.** Each fire is a new session, so repair state lives in the git branch `claude/job-<id>` and in the fire payload.
- **Network:** the routines' cloud environment uses Custom network access: the default package-manager list plus our FastAPI hostname, for callbacks.
- **Limits (research preview, may change):** 30 fires/hour per routine, 100 API fires/hour per account; runs draw from subscription usage.

Exact payloads, routine prompts and callback contracts are in [`ROUTINES.md`](ROUTINES.md).

---

## 5. Repositories & trust boundaries

| Repo / service | Contains | Secrets | Who writes |
|---|---|---|---|
| `automation-maker` (private) | Everything: spec, engine, blocks, catalog, tools, build, api, web, worker | Environments: `sync` (sync token), `catalog` (R2 write, catalog signing key); later the Runner code-signing certificate | Us (developed with Claude Code on the web) |
| `automation-builds` (private) | `main`: synced snapshot of `engine/ spec/ tools/ build/` + workflows. Job branches `claude/job-<id>` contain only `jobs/<id>/` | Environments: `publish` (R2 write, callback HMAC secret, jobs signing key), `layers` (R2 write, callback HMAC secret) | `main`: sync workflow from `automation-maker`. Job branches: the `am-build` routine |
| Cloudflare Worker `makemyexe-download` | Download merge (§8.6) | R2 bucket binding (read), `DOWNLOAD_TOKEN_SECRET` (shared with the API) | Deployed from `worker/` |

All GitHub secrets are **environment** secrets restricted to `main` (and `engine-v*` tags for `sync`), never repository secrets: a job branch could add its own workflow file, and that workflow could read every repository secret.

**Why the build is safe even though the routine pushes branches:** the workflows are started by `workflow_dispatch` on `main`, so the workflow file always comes from `main`. Job 1 copies **only** `jobs/<id>/` from the job branch, so a job branch can't change the engine, tools or workflow. Generated code runs only in Job 1, which has no secrets. Third-party library code (layers) is imported only in jobs without secrets as well.

**Why signing lives in the publish jobs, not the API:** the API is the internet-facing part. The publish jobs only hash and sign files they treat as data, run from `main`, and hold the key in a `main`-only environment. Two keys (`catalog`, `jobs`) limit the damage if one leaks.

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
| App builds | GitHub Actions `ubuntu-latest` in `automation-builds` (pack builds) |
| Windows builds | GitHub Actions `windows-latest`: Runner releases, native layer checks, standalone fallback |
| Storage | Cloudflare R2 (private): runner, layers, packs (§8.6 layout) |
| Downloads | Cloudflare Worker (`worker/`), streams a merged zip from R2 with an API-issued token |
| Desktop engine | Python 3.12 + PySide6 (Qt Widgets), frozen once per release as the Runner |
| Doc/PDF/Excel libs | Core in the Runner: pypdf, reportlab or fpdf2, Pillow. Others as layers: openpyxl, python-docx, pikepdf, ... |
| Packaging | Runner: PyInstaller `--onedir` once per engine release. Apps: signed `.mmx` packs. Standalone per-app PyInstaller build only as a fallback |
| Signing | Ed25519 for packs (`openssl pkeyutl` in the publish jobs); code-signing certificate for the Runner (live) |
| Checks | Ruff, pytest (Qt offscreen), Bandit, pip-audit, AST rules incl. import allowlist (`tools/check_job`) |
| Hosting (web) | Cloudflare Pages (static `web/dist`, auto-deploy from `main`) |
| Hosting (API) | Render web service from `api/Dockerfile` (`render.yaml` blueprint) |
| Keep-awake | cron-job.org: `GET /health` every 10 min (watchdog itself runs in-process) |

### 6.1 Free hosting for the internal phase (₹0)

| Part | Host | Free-tier facts that matter |
|---|---|---|
| Web | Cloudflare Pages | Unlimited bandwidth, never sleeps, free custom domain |
| API | Render free web service (Docker) | Sleeps after 15 min idle (30–50 s cold start); 750 instance hours/month; 500 build minutes/month; 512 MB RAM; no persistent disk |
| DB + Auth | Supabase free | Pauses after ~1 week with no DB activity; resume from the dashboard |
| Storage | Cloudflare R2 | 10 GB-month free, free egress; needs a card or PayPal on the account; no hard cap, only alerts (lifecycle rules + storage check keep it small) |
| Downloads | Cloudflare Workers | 100k requests/day; ~10 ms CPU per request (bytes are piped, not processed: §8.6) |
| CI | GitHub Actions (private repos) | 2,000 min/month; Linux counts 1×, Windows 2×, so app builds run on Linux |
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

## 8. Desktop engine & delivery: Runner + packs

> **Decided 2026-10-17** (Phases 2b and 2c, §13). It replaces one PyInstaller build per automation. Until 2b ships, the current per-automation EXE pipeline and the presigned R2 downloads stay live.
>
> **Built so far (2b, part 1):**
> - the pack format and verification (`engine/pack.py`, `engine/ed25519.py`: pure-Python Ed25519, so the Runner needs no crypto library);
> - pack making and signing (`build/pack.py`, standard library + `openssl pkeyutl`);
> - the Runner build (`build/runner.py`) and Runner start-up rules (`engine/__main__.py`);
> - the Linux app check (`build/pack_check.py`);
> - CI: `packs (Linux)` checks and signs every app with a throwaway key; `runner (Windows)` builds the Runner and runs every pack, refuses tampered copies and a plain `spec.json`, and opens the real window.
>
> **Built in part 2 so far:**
> - zip entry blocks (`build/zipblocks.py`);
> - the download Worker (`worker/`), with the manual deploy workflow `worker.yml`;
> - download tokens in the API (`api/downloads.py`). A catalog manifest entry with a `pack` field (`{prefix, runner, layers, exe, size_bytes}`) is served through the Worker once `DOWNLOAD_WORKER_URL` and `DOWNLOAD_TOKEN_SECRET` are set.
>
> **Still to do:** publishing the Runner, catalog packs and job packs as blocks (with the signing keys), the R2 lifecycle rules, and the switch of `build.yml` and the `am-build` prompt.

Two details settled while building part 1:
- A pack also carries `samples/` (tiny fake files), so the release gate can smoke-test every pack with a new Runner.
- The publish job builds the pack from the app folder at the pinned commit, read as data, never from Job 1's artifact. Generated code ran in Job 1 and could have changed its own output after the checks.

What the user downloads (one zip; extract, double-click; no install):
```text
InvoiceGenerator.zip
├── InvoiceGenerator.exe   the Runner: byte-identical for every app, only the file name differs
├── _internal/             Python 3.12 + Qt + engine + core libraries, identical for every app
├── libs/<dist>-<ver>/     library layers this app needs, and only those (§8.4)
├── app.mmx                this app: signed manifest + spec.json + optional custom_step.py + assets
└── Guide.pdf
```

**Why:** 99.9% of a per-automation EXE is the same Python + Qt runtime; the automation itself is a few KB. Freezing the runtime once means:
- App builds run on Linux in a few minutes instead of a ~10-minute Windows PyInstaller build.
- R2 stores KB per app instead of ~50 MB, so the 10 GB free tier stops being a limit.
- GitHub's free minutes stop being a limit: Linux minutes count 1×, Windows 2×.
- SmartScreen and code-signing reputation build up on one binary, because the exe hash is the same for every app.
- A block bug fix reaches every app on its next download.

The user still gets one EXE per app.

### 8.1 Engine (inside the Runner)
- **Standard UI shell:** header -> first-time setup (settings) -> inputs form -> preview (if files change) -> Run -> result (open file/folder, undo).
- **Block library v1:** `form.*`, `settings.*`, `counter.*`, `calc.*`, `pdf.render_template`, `pdf.merge/split/compress/watermark/encrypt`, `image.*`, `excel.read/write/combine/dedupe/compare/split/summary`, `convert.*`, `files.scan/rename/organize/find_duplicates`, `file.save`, `undo.*`.
- **Custom-step context API** (`engine/custom_api.py`): read user-selected inputs, write only to the output folder, move only through the undo log; no delete, no subprocess, no network unless declared.
- **Custom-step sandbox** (`engine/sandbox.py`): while generated code runs (module level included), a Python audit hook refuses writes outside the output folder, deletes, renames, starting programs, native libraries and (unless declared) network connections. It backs up the static rules in `tools.check_job`.
- **Offline guard:** enforced at start-up from the pack's spec, before any pack code loads. With `network.required = false`, sockets are blocked; with `true`, only the listed domains are allowed. Network libraries are never in the core Runner; a network app gets them as layers. Generated code importing `socket/urllib/requests/http*` fails the checks unless the spec declares network.
- **Guide mode:** `--guide-mode out/` renders every screen with `sample_data` and saves screenshots; the build produces `Guide.pdf`.
- **One look everywhere:** the engine forces Qt's Fusion style and bundles its fonts (Noto Sans + Noto Sans Devanagari). Guide screenshots rendered on Linux then match what users see on Windows.
- **Local data:** settings JSON + SQLite (counters, saved customers) in `%APPDATA%`, never sent anywhere.
- **Start-up:** the Runner loads `app.mmx` from the folder of its own exe, never from the current directory. If the pack is missing, it shows "This folder is incomplete, download the app again". If it was started from inside a zip (Explorer's temp extraction), it shows "Extract the zip first, then open the app".

### 8.2 Pack format (`app.mmx`)
A zip with:

| File | Contents |
|---|---|
| `manifest.json` | `format` (1), `id`, `version`, `title`, `kind` (`catalog` \| `job`), `runner` (`major`, `tested_with`), `network` summary, `files` (`{path: sha256}` for every other file in the pack), `layers` (`[{dist, version, record_sha256}]`), `key_id`, `created_at` |
| `manifest.sig` | Ed25519 signature over the exact bytes of `manifest.json` |
| `spec.json` | The AutomationSpec |
| `custom_step.py` | Optional |
| `assets/` | Optional templates and images |

Never any user data (format, not data). Settings live in `%APPDATA%`, so the user never edits the pack and the signature never gets in the way.

### 8.3 Pack signing
- **Two Ed25519 keys:**
  - `catalog` signs ready-made apps. It lives in the automation-maker environment `catalog`.
  - `jobs` signs custom apps. It lives in the automation-builds environment `publish`.

  Only those publish jobs, which never run generated code, hold a private key. The API and the routines never see one.
- **Verification:** the Runner embeds the public keys with their ids. On every start, before loading anything from the pack:
  1. Verify `manifest.sig` with the key named by `key_id`.
  2. Check every pack file's sha256.
  3. For every layer, check that the sha256 of its `RECORD.json` equals `record_sha256`, that every file in `libs/<dist>-<ver>/` is listed in `RECORD.json` with a matching hash, and that nothing unlisted is present.

  Any mismatch means refuse to run: "This app was changed after MakeMyEXE made it. Download it again from makemyexe.com." Verification is fully offline.
- **Import path:** `sys.path` holds only `_internal` and the verified layer folders. The exe's folder is never importable. `custom_step.py` is loaded by explicit path from the verified pack.
- **What a signature proves:** origin and integrity, not safety. Safety comes from the build gates (§9).
- **Rotation and revocation:** keys have ids, and a Runner release can drop a key. There's no online revocation (offline rule): a withdrawn app can only be blocked from future downloads.

### 8.4 Library layers
- **The core Runner holds** Python 3.12, the stdlib, PySide6 (trimmed), the engine and the core libraries. The exact list is the Runner lock (`build/runner.lock`, resolved for `win_amd64`, Python 3.12).
- **Everything else is a layer:** one folder per distribution, `libs/<dist>-<version>/`, unpacked from its Windows wheel, plus a `RECORD.json` of file hashes. Accepted wheels: `cp312-win_amd64`, `abi3-win_amd64` or `py3-none-any`. Never sdists, so no install script ever runs. Each layer is stored once in R2 and shared by every pack.
- **Resolution:** a pack declares the top-level distributions it imports in `jobs/<id>/requirements.txt` (names only). The API resolves the full set, transitive dependencies included, in one pass with the Runner lock as constraints (`uv pip compile --python-platform windows --python-version 3.12 -c build/runner.lock`). That way layers never conflict with the Runner or with each other. The pack manifest pins every resulting layer.
- **Building a layer:** `layer.yml`, on automation-builds `main`, is dispatched by the API.
  - Job 1 (ubuntu, no secrets): the policy gate (§8.5), then download with `--require-hashes`, unpack, and write `RECORD.json`.
  - Job 1b, native wheels only (windows-latest, no secrets): import each module with the released Runner (`MakeMyEXE.exe --import-check <module>`). This runs once per layer, ever.
  - Job 2 (environment `layers`, never imports layer code): upload `layers/<dist>/<version>/` and send the HMAC callback.
- **Testing packs on Linux:** install the same pinned versions (Linux wheels) on top of the Runner lock. Native libraries were already import-checked on Windows when their layer was built.

### 8.5 Library policy gate (no human in the loop)
The gate runs in `layer.yml` Job 1, which is trusted code from `main`. The routine only declares names; it never decides.

1. **Pre-approved:** `build/libs.toml` is reviewed in PRs: ~200 office, PDF, Excel, image and text libraries, each with its license noted. These skip the popularity checks in step 2 but still go through OSV and hash pinning.
2. **Anything else must pass every check:**
   - It's on PyPI.
   - It isn't a typosquat: edit distance ≤ 2 to a top-5,000 package name it isn't (hugovk/top-pypi-packages).
   - Its first release is ≥ 365 days old.
   - The chosen release is ≥ 14 days old. Pick the newest release that is.
   - It had ≥ 50k downloads last month (pypistats).
   - OSV (`api.osv.dev/v1/query`) has no advisory for that version, including `MAL-` entries.
   - Its license is in the allowlist: MIT, BSD-2/3-Clause, Apache-2.0, PSF-2.0 or ISC.
   - It has a Windows wheel as described in §8.4.
   - It resolves against the Runner lock.

   Thresholds are settings. Each decision is stored with the facts it used.
3. **Review afterwards:** auto-approved libraries go onto a weekly review list (admin page). Revoking marks a layer withdrawn: no new download includes it, and jobs that need it show a clear message. Copies already downloaded can't be revoked (offline).

**Residual risk:** a popular package's release can be compromised (for example ultralytics on PyPI, December 2024). Release age, hash pins and OSV reduce this risk; they don't remove it.

Time added for the user: 0 when the layers exist, ~30 s for the first user of a pre-approved library, ~1–2 min for a new library that passes, plus ~3 min once per native library for the Windows import check.

**When a library is missing or rejected:**

| Why | Path |
|---|---|
| Policy reject (license, age, popularity, OSV, typosquat) | Repair fire: "rewrite without it", listing what's available. If it's still needed: `needs_library` (human). **Never** the standalone build, which would bypass the gate |
| Technical: no Windows wheel, or a conflict with the Runner lock, for an otherwise approved library | Standalone build: the old per-app PyInstaller pipeline on windows-latest (`kind: standalone`), deleted after 14 days |
| Not a Python library (Tesseract, Ghostscript) | Binary layer, only through a `libs.toml` PR (human) |
| Needs installed software (Word/Excel COM) | The spec declares it; the app checks at start-up and explains what's missing |

### 8.6 Downloads: merge in a Cloudflare Worker
R2 layout:
```text
runner/<version>/exe.bin, internal.bin, layout.json   Runner as pre-built zip entry blocks
runner/latest-<major>.json                             pointer, flipped only after the release gate (§8.7)
layers/<dist>/<version>/blocks.bin, layout.json, RECORD.json
packs/catalog/<id>/<version>/app.mmx, Guide.pdf        latest 2 versions kept per app
packs/jobs/<job_id>/attempt-<n>/app.mmx, Guide.pdf     lifecycle rule: delete after 14 days
standalone/jobs/<job_id>/...                           lifecycle rule: delete after 14 days
```

- **Token:** the API (`POST /automations/{id}/download`, and job downloads) returns a Worker URL carrying a token: HMAC-SHA256 with `DOWNLOAD_TOKEN_SECRET` over {runner version, layer keys, pack key, file name, `exp` = now + 15 min}. The API decides what goes in; the Worker only verifies and streams.
- **The Worker** is bound to the bucket and holds no R2 keys. It writes one zip:
  1. A freshly written local header for `<AppName>.exe` (the rename), followed by the exe's compressed bytes, unchanged.
  2. The `_internal/` entry block and the layer entry blocks, unchanged.
  3. Local entries for `app.mmx` and `Guide.pdf`.
  4. A central directory built from the precomputed records in each `layout.json`, with offsets shifted.

  `Content-Length` is exact, so the browser shows progress. No Zip64 is needed (< 4 GB).
- **CPU budget:** the free plan allows ~10 ms CPU per request. R2 bodies are piped through without touching the bytes; only the headers and the central directory (a few thousand records) are built in JS. If that ever exceeds the limit, fall back to Workers Paid ($5/month) or a browser-side merge.
- **`layout.json`** is produced by the trusted publish steps from the zip they upload (data, not code).

### 8.7 Runner releases and versioning
- **Builds:** the Runner version is the engine version (tag `engine-v<semver>`). It's built on windows-latest by a trusted release workflow, with a launch check using a sample pack.
- **Minor releases only add** blocks, bundled libraries and API. They never remove or change behaviour that packs rely on. Changing a bundled library's version re-resolves every layer, and a layer that no longer resolves blocks the release. Anything else is a major release.
- **Merge rule:** a pack records `runner.major` and `tested_with`. The Worker merges the newest Runner of that major (`latest-<major>.json`).
- **Release gate:** before `latest-<major>` moves, every catalog pack and every non-expired job pack runs `--smoke-test` with the new Runner on Windows. Any failure blocks the flip.
- **Rollback:** the previous Runner of each major stays in R2, so a rollback just flips the pointer back.

### 8.8 Size and memory budget
These are estimates. CI must measure real sizes, and fail a Runner release that exceeds the budget.

| Part | On disk | Zipped download |
|---|---|---|
| Python 3.12 runtime + stdlib | ~12 MB | ~5 MB |
| PySide6 trimmed (Core/Gui/Widgets, `qwindows`; no WebEngine, QML, 3D, multimedia, `opengl32sw`) | ~40 MB | ~17 MB |
| Engine + fonts | ~3 MB | ~2 MB |
| Core libraries (pypdf, reportlab, Pillow) | ~15 MB | ~6 MB |
| **Core Runner (budget)** | **≤ 80 MB** | **≤ 35 MB** |

Typical layers: openpyxl ~4 MB, python-docx + lxml ~15 MB, pikepdf ~18 MB, pandas + numpy + tzdata ~80 MB, opencv-headless ~90 MB, Tesseract with eng + hin data ~70 MB.

**Why layers, not one big Runner:** bundling all ~200 pre-approved libraries would make every app ~500 MB on disk. With layers, a PDF or invoice app stays ~70 MB on disk (~30 MB download); an Excel app ~75 MB; a pandas report app ~150 MB; OCR ~220 MB. All layers together in R2 take about 1 GB, stored once.

**RAM:** Python loads only what is imported, and blocks load lazily, so libraries on disk cost no RAM until a step uses them. A Qt Widgets app at idle uses ~50–70 MB; a typical office task peaks at ~100–150 MB. Heavy imports add on top: pandas + numpy ~+80 MB, opencv ~+80 MB. All of this fits a 4 GB PC.

**Start-up cost of verification:** SHA-256 runs at several hundred MB/s, so checking a pack plus an 80 MB layer adds ~0.2 s per start.

**Disk on the user's PC:** every app folder carries its own Runner (~70 MB). That's the price of "no install". A later optional shared Runner install could de-duplicate it for users with many apps.

---

## 9. Build & validation gates

1. **Spec validation** (`tools.validate_spec`): schema, known blocks, allowed category, network rules. Run by `am-spec` before callback and by FastAPI on receipt.
2. **Job checks on Linux** (`tools.check_job`, run inside the `am-build` session): folder layout, spec + sample files, AST rules (allowlisted imports, no dynamic code or dunder access), Ruff, Bandit, pytest with `sample_data`, the engine's smoke test. The import allowlist is the stdlib, `engine.custom_api`, the Runner lock and the job's declared requirements.
3. **Library resolution** (FastAPI): the layers exist, or `layer.yml` builds them through the policy gate (§8.4–8.5).
4. **Pack Job 1** (`ubuntu-latest`, no secrets), pinned to the commit that passed those checks and to the fingerprint of the spec the user confirmed (a later push or a changed spec fails at `validate`):
   - Check out `main`, plus only `jobs/<id>/` from the job branch.
   - Install the Runner lock and the resolved layers.
   - Run `tools.check_job` again: the session's result isn't trusted.
   - Smoke test on `sample_data`, then guide mode -> `Guide.pdf`.
   - Upload the pack files and `report.json` as an artifact.

   It never uses a writable cache. To speed up installs, use an immutable container image built by the trusted engine release workflow.
5. **Pack Job 2** (environment `publish`, never runs generated code): write the manifest with hashes, sign it with the `jobs` key, upload to `packs/jobs/...`, and send the HMAC callback.
6. **Repair:** FastAPI fires `am-build` in `repair` mode with the report; max 2 repairs.
7. **Only passing, signed packs are downloadable.** Download tokens expire after 15 minutes. Job packs expire after 14 days; the saved spec can be rebuilt.

**Standalone fallback (§8.5):** the current Windows PyInstaller Job 1 + Job 2 (live today, pinned the same way), used only for technical library failures.

---

## 10. API (FastAPI)

| Method | Path | Purpose |
|---|---|---|
| GET | `/automations` | Catalog list |
| GET | `/automations/{id}` | Details, badge, guide |
| POST | `/automations/{id}/download` | Download token -> Worker URL (presigned R2 link until Phase 2b) |
| POST | `/jobs` | New custom job from a description -> fires `am-spec` -> `202 {job_id}` |
| GET | `/jobs/{id}` | Status, spec, assumptions, questions, attempts (with session links), download |
| POST | `/jobs/{id}/answers` | Answer questions -> spec revision (fires `am-spec`) |
| PUT | `/jobs/{id}/spec` | Save the user-edited spec (validated) |
| POST | `/jobs/{id}/confirm` | Confirm spec -> fires `am-build` |
| GET | `/me/jobs` | The user's custom automations |
| POST | `/internal/routine-callback` | From routines; per-job bearer token |
| POST | `/internal/build-callback` | From GitHub Actions Job 2 (pack, standalone); HMAC signature |
| POST | `/internal/layer-callback` | From `layer.yml` Job 2: layer ready or rejected (with the policy facts); HMAC signature |
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

Both providers end up calling the same handlers: `JobService.on_spec_ready(...)` and `JobService.on_generation_done(...)`. A library rejection reuses `request_repair` with a report whose stage is `library`.

---

## 12. Repository layout (`automation-maker`)

```text
automation-maker/
  CLAUDE.md
  docs/ARCHITECTURE.md
  docs/ROUTINES.md      routine prompts, payloads, callback contracts, cloud environment setup
  docs/SPEC_GUIDE.md    how to design specs; read by am-spec
  spec/                 Pydantic AutomationSpec models + JSON Schema export + block catalog
  engine/               PySide6 shell, block library, custom_api, runtime guards, guide mode, pack loader + verifier
  tools/                validate_spec, check_job (lint/test/AST rules, import allowlist)
  automations/          ready-made catalog: one folder per automation (spec.json, templates, tests)
  build/                runner build + runner.lock, pack build + signing, layer build + policy gate, libs.toml,
                        guide PDF generator, standalone PyInstaller fallback
  api/                  FastAPI app (JobService, GenerationProvider, callbacks, library resolution, download tokens)
  web/                  React + Vite frontend
  worker/               Cloudflare Worker: download merge (§8.6)
  builds-repo/          source for automation-builds main: build.yml, layer.yml, README
  .github/workflows/
    ci.yml              lint + tests; catalog packs; publish catalog
    sync-builds.yml     pushes engine/spec/tools/build + builds-repo/ to automation-builds main
    runner.yml          Runner release on engine-v* tags + release gate
```

---

## 13. Development phases

| Phase | Goal | Done when |
|---|---|---|
| 0 | Repo, CLAUDE.md, CI skeleton | CI runs Ruff + pytest |
| 1 | **Spec models + engine + 3 automations** (Invoice, PDF Merge, Bulk Rename) | They run on Windows from `spec.json` |
| 2 | Windows packaging + guide mode; `automation-builds` repo + `build.yml` | A manual dispatch produces a zip + Guide.pdf |
| 2b | **Runner + packs:** Runner build + release gate, pack format + signing + verification, Linux pack builds (catalog and jobs), Worker download merge, R2 layout + lifecycle | Catalog downloads come from the Worker; a job's pack builds on Linux and runs in the downloaded Runner on Windows; a tampered pack is refused |
| 2c | **Library layers + policy gate:** `runner.lock`, `libs.toml`, `layer.yml`, resolution in the API, `needs_library`, admin review list | A custom step importing a pre-approved library and one importing a new library both reach `ready` without a human; a rejected library triggers the rewrite repair |
| 3 | FastAPI jobs + callbacks + `RoutineProvider`; routines `am-spec` and `am-build` set up | Description -> spec -> EXE end-to-end, triggered from curl |
| 4 | Web: catalog, job flow with spec preview/edit, downloads | Full Flow B in the browser |
| 5 | Rest of Wave 1 catalog + repair loop hardening + watchdog | 9 automations; failing jobs repair or fail cleanly |
| 6 | Live phase: `ClaudeApiProvider`, Runner code signing, hosting, rate limits | Public beta |

Do 2b before setting up the routines in Phase 3, so `build.yml` and the `am-build` prompt change only once.

---

## 14. Open decisions

- Pricing: free catalog + paid custom builds, or a subscription.
- Buy makemyexe.com (name decided: MakeMyEXE).
- Code-signing route (country/business registration).
- Before the Runner gets a code-signing certificate, harden the folder around the signed exe:
  - **DLL side-loading:** a signed exe shipped as a folder will load a planted DLL that sits beside it. Use a bootloader built with a restricted DLL search order.
  - **Integrity of `_internal/`:** Authenticode covers only the exe, so the DLLs and `.pyd` files in `_internal/` must be verified at start-up against a hash list compiled into the exe (~0.1–0.3 s).
- Contents of `build/libs.toml` (the first ~200 pre-approved libraries) and the core Runner lock.
- Live-phase API host: Render Starter vs Cloud Run (internal phase is decided: §6.1).
- Later: online automations (🌐) with a domain allowlist; macOS.
