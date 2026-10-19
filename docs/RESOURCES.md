# MakeMyEXE: Resources, and why we use each one

Every account, service, repo, environment, secret, key, token and workflow MakeMyEXE depends on, what it's for, why we picked it, what it may touch, and what happens if it leaks. The other two docs say how the product works: [ARCHITECTURE.md](ARCHITECTURE.md) (the whole system) and [DESKTOP_APP.md](DESKTOP_APP.md) (the installed app and how automations reach it). The step-by-step setup is in [DEPLOY.md](DEPLOY.md); this doc doesn't repeat it, it points to it.

**Status** (checked 2026-10-18 against GitHub, the live API and the Worker): ✅ live · ⚠️ set up but incomplete · ❌ not done yet · 🔜 planned for later. Update the status column whenever something changes.

> **No secret values in this file, ever.** Only names, places and permissions. Values live only in the dashboards and GitHub environments named below (CLAUDE.md, DEPLOY.md).

---

## 1. The map

```
                   ┌──────────────── Cloudflare ────────────────┐
 Browser ─────────▶│ Pages: makemyexe.pages.dev (website)        │
   │               │ Worker: makemyexe-download (streams files)  │◀── signed link
   │               │ R2: makemyexe-builds (private file store)   │
   │               └──────────▲───────────────▲──────────────────┘
   │ API calls                │ read-only     │ upload (Actions only)
   ▼                          │               │
 Render: makemyexe-api ───────┘     GitHub Actions (automation-maker, automation-builds)
   │  ▲                                   ▲
   │  └── cron-job.org pings /health      │ build dispatch, callbacks
   ▼                                      │
 Supabase (Mumbai): Postgres + login   Claude Code routines (am-spec, am-build) 🔜
```

The user's PC talks to none of this after the download: the MakeMyEXE app has no network code (DESKTOP_APP.md §3).

---

## 2. Services and accounts

| Service | Plan / cost | What we use it for | Why this one | Limits to watch | Status |
|---|---|---|---|---|---|
| **GitHub** (2 private repos, Actions) | Free | Code, CI, Windows builds, signing, publishing | Actions gives free `windows-latest` runners, which PyInstaller and Inno Setup need; environments keep secrets per branch | 500 MB artifact storage (DEPLOY.md §10); 2,000 Actions min/month on private repos, Windows minutes count ×2; **no rulesets or branch protection on private repos** (§9) | ✅ |
| **Render** (`makemyexe-api`, Singapore) | Free web service | The FastAPI API (Docker, `render.yaml`) | Runs our Docker image as is, free, deploys from `main`; Singapore is closest to Supabase Mumbai | 512 MB RAM, sleeps after 15 min idle, 750 h/month: the only free service on the account | ✅ |
| **Supabase** (Mumbai) | Free | Postgres (jobs, specs) + login (email/password, email code, Google) | Auth and DB in one, JWKS for the API, RLS; Mumbai is closest to users | 500 MB DB; paused after ~1 week without DB activity; built-in mailer only a few emails/hour | ✅ |
| **Cloudflare Pages** (`makemyexe`) | Free | The website (`web/`, static build) | Free, global CDN, auto-deploy from `main`, previews per PR | Build-time env vars only (redeploy after a change) | ✅ |
| **Cloudflare R2** (`makemyexe-builds`) | Free tier, card/PayPal on file | Private file store: catalog apps, Runner, packs, installer | **Free egress** (downloads cost nothing), S3 API, same account as the Worker | 10 GB-month, then billed: no hard cap, so watch Metrics and set a budget alert | ✅ |
| **Cloudflare Worker** (`makemyexe-download`) | Free | Streams downloads (zip, `.mmx` bundle) from R2 | Reads R2 inside Cloudflare (no egress, no Render RAM); checks the API's token | 100k requests/day, CPU time per request | ✅ deployed 2026-10-18 |
| **cron-job.org** | Free | `GET /health` every 10 min | Keeps Render awake so the watchdog runs; GitHub cron would burn Actions minutes | ~744 h/month, inside Render's 750 | ✅ |
| **Claude subscription** (Claude Code on the web) | Your plan | Development sessions; later the `am-spec` / `am-build` routines | Internal phase costs nothing extra: subscription, not API billing | Routines: 30 runs/hour each, count toward plan usage | ✅ dev · 🔜 routines |
| **Google Cloud** (OAuth client) | Free | "Continue with Google" through Supabase | Most users have Google | Consent screen must be published (verification for wider use) | check (DEPLOY.md §1) |
| Domain `makemyexe.com` | ~₹1k/yr | Site, mail sender, Worker route | Trust, email deliverability | Trademark check before buying | 🔜 |
| Mail service (Resend / Brevo / SES) | Free tier | Supabase login emails via SMTP | Supabase's built-in mailer is for testing only | Needs the domain | 🔜 deferred |
| Code-signing certificate (OV, cloud HSM) | Paid, yearly | Signs the installer and app exe (Authenticode) | Smart App Control blocks unsigned apps; SmartScreen trust builds up | Buy a few weeks before launch | 🔜 live phase |
| Payment gateway | Per transaction | Paid automations | — | — | 🔜 phase 2e / live |
| Claude API + Managed Agents | Pay per use | Live-phase spec chat and builds | Replaces routines at launch (ARCHITECTURE.md §11) | — | 🔜 live phase |

---

## 3. Repositories, and why two

| Repo | Holds | Who writes | Why separate |
|---|---|---|---|
| `automation-maker` (private) | Everything we write: `spec/ engine/ api/ web/ worker/ build/ tools/ automations/`, docs | Us (Claude Code dev sessions, PRs) | Holds the important secrets (catalog signing key, R2 write, Worker deploy) |
| `automation-builds` (private) | `main`: a snapshot of our engine and build workflow (made by *Sync*). `claude/job-<id>` branches: one custom app each | `main`: only *Sync*. Job branches: the `am-build` routine | **AI-generated code runs here.** It must never run next to automation-maker's secrets. The build job that runs generated code has no secrets; only the later publish job does, from `main` |

---

## 4. GitHub environments and their secrets

Secrets are **environment** secrets restricted to `main`, never repository secrets (a job branch could add a workflow that reads every repository secret). Create the environment with its branch rule **before** adding secrets; a workflow naming a missing environment creates it unprotected (DEPLOY.md §5).

| Repo › environment | Branch rule | Secrets / variables | Used by | Why it's here | Status |
|---|---|---|---|---|---|
| automation-maker › `catalog` | `main` | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` (upload token), `PACK_SIGNING_KEY` (catalog-1) | CI *publish catalog*, *Release* | Signs and uploads our own apps and the installer, only from `main` | ✅ |
| automation-maker › `worker` | `main` | `CLOUDFLARE_API_TOKEN`, `CLOUDFLARE_ACCOUNT_ID`, `DOWNLOAD_TOKEN_SECRET` | *Deploy download Worker* | Deploying the Worker and giving it its secret | ✅ |
| automation-maker › `sync` | `main`, tag `engine-v*` | `BUILDS_SYNC_TOKEN` | *Sync automation-builds* | The only way anything reaches automation-builds `main` | ✅ token set 2026-10-18 |
| automation-builds › `publish` | `main` | `PACK_SIGNING_KEY` (jobs-1); later `R2_*` (upload), `BUILD_CALLBACK_SECRET`, variable `API_BASE_URL` | *Build* workflow's publish job | Signs and uploads custom apps after the secret-free build job passed | ⚠️ signing key only |
| automation-builds › `layers` | `main` | `R2_*`, `BUILD_CALLBACK_SECRET` | Library layer builds (phase 2c) | Same split: library code runs only in jobs without secrets | 🔜 phase 2c |
| automation-maker › `main - makemyexe-api` | — | none | Created automatically by a deploy integration (Render's deploy status) | Not ours; keep it empty | ✅ (empty) |

Repository secrets: **empty in both repos**, and they must stay empty.

---

## 5. Render and Cloudflare settings

**Render › makemyexe-api › Environment** (full list: `render.yaml`, DEPLOY.md §2):

| Name | What it is | Why | Status |
|---|---|---|---|
| `DATABASE_URL` | Supabase session pooler URI (with DB password) | Direct connection is IPv6-only; Render can't reach it | ✅ |
| `SUPABASE_URL` | Project URL | The API checks login tokens with its JWKS | ✅ |
| `PUBLIC_BASE_URL`, `CORS_ORIGINS` | API URL, site URL | Callbacks; only our site may call the API from a browser | ✅ |
| `CALLBACK_TOKEN_SECRET` | random 32 bytes | Signs per-job callback tokens for the routines | ✅ |
| `BUILD_CALLBACK_SECRET` | random 32 bytes | HMAC on `/internal/build-callback`; the same value goes into automation-builds `publish` | ✅ in Render · ❌ in `publish` |
| `PROVIDER`, `DEV_AUTH` | `fake`, `false` | `routine` once routines exist; `DEV_AUTH` is never true here (the API refuses to start) | ✅ |
| `R2_*` (4) | **Read-only** R2 token | Signs download links; can't change or delete a file | ✅ |
| `DOWNLOAD_WORKER_URL`, `DOWNLOAD_TOKEN_SECRET` | Worker URL, shared secret | The API issues 15-minute Worker links; same secret as the Worker | ✅ 2026-10-18 |
| `ROUTINE_SPEC_URL/TOKEN`, `ROUTINE_BUILD_URL/TOKEN` | Routine API triggers | The API starts `am-spec` / `am-build` | ❌ (routines) |
| `BUILDS_GITHUB_TOKEN` | Fine-grained, Actions: write on automation-builds only | The API starts the *Build* workflow | ❌ (routines) |
| `LICENSE_SIGNING_KEY` | Ed25519 private key | Offline licenses for paid automations | 🔜 phase 2e |

**Cloudflare Pages › makemyexe › Variables** (DEPLOY.md §3): `NODE_VERSION`, `VITE_API_URL`, `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY` (the **publishable** key), optional `VITE_CONTACT_EMAIL`. Everything `VITE_` is public in the JavaScript, so only browser-safe values go here.

**Cloudflare Worker › makemyexe-download**: secret `DOWNLOAD_TOKEN_SECRET` (set by the deploy workflow), R2 binding `BUCKET` (read). It holds no R2 keys.

---

## 6. Every credential: what it can do, and the damage if it leaks

| Credential | Lives in | Can do | If it leaks | Expiry / rotation |
|---|---|---|---|---|
| **catalog-1** (Ed25519 private) | `catalog` env + your offline backup | Seal ready-made automations the app trusts | Someone could sign a malicious "catalog" app our app would run | No expiry. Rotate: new id `catalog-2` in `build/trusted_keys.json`, new key in `catalog`, Runner/app release |
| **jobs-1** (Ed25519 private) | `publish` env + offline backup | Seal custom automations | Same, for custom apps | Same, `jobs-2` |
| Their public halves | `build/trusted_keys.json`, inside the app | Only **check** a seal | Nothing: public by design | — |
| **license** key 🔜 | Render `LICENSE_SIGNING_KEY` | Seal "automation X is licensed to install Y" | Forged licenses (lost revenue), **never** running code | Rotate with an app release |
| R2 upload token (`makemyexe-publish`) | `catalog` (and later `publish`, `layers`) | Read/write/delete objects in `makemyexe-builds` only | Overwrite or delete downloads (packs are still sealed: a swapped file fails the app's check) | Rotate in R2 › API tokens, update the environments |
| R2 read-only token (`makemyexe-api`) | Render | Read objects | Someone downloads our builds without a link (they're free apps; no user data in R2) | Rotate in R2, update Render |
| `DOWNLOAD_TOKEN_SECRET` | Render + Worker (via `worker` env) | Make valid Worker download links | Free downloads of anything in the bucket, including paid bundles later | Change in both places together, then redeploy the Worker |
| `CALLBACK_TOKEN_SECRET` | Render | Sign routine callback tokens | Fake spec/build results posted to jobs | Change in Render |
| `BUILD_CALLBACK_SECRET` | Render + `publish` | Sign build-finished callbacks | Fake "build done" with a wrong link | Change both together |
| `BUILDS_SYNC_TOKEN` | `sync` env | Push to automation-builds, incl. workflows | **High:** a pushed workflow on `main` could read `publish`, including jobs-1 | 90 days to 1 year; GitHub emails before expiry. Better before launch: a GitHub App (1-hour tokens) |
| `BUILDS_GITHUB_TOKEN` 🔜 | Render | Start workflows in automation-builds | Someone starts builds (Actions minutes) | Set an expiry, renew in Render |
| `CLOUDFLARE_API_TOKEN` | `worker` env | Edit Workers on our account | Replace the Worker (it could hand out other files; packs stay sealed) | Rotate in Cloudflare › API Tokens |
| Routine tokens 🔜 | Render | Start `am-spec` / `am-build` runs | Burn your Claude plan usage | Regenerate in the routine's trigger |
| Supabase DB password | Inside Render's `DATABASE_URL` | Full database access | All jobs and specs readable (no user files: we never take data) | Reset in Supabase, update Render |
| Supabase publishable key | Pages (public) | What RLS allows: nothing on our tables | Nothing: public by design | — |
| Supabase secret key | **Not used anywhere, ever** | Bypasses RLS | — | — |
| Google OAuth client secret | Supabase provider settings | Google sign-in for our app | Phishing-style sign-in screens in our name | Rotate in Google Cloud, update Supabase |
| Code-signing certificate 🔜 | Cloud HSM (never a file) | Make Windows trust an exe as ours | Malware signed as MakeMyEXE: revoke at once | Yearly renewal |

**Where the private `.pem` files go:** not in OneDrive or any synced folder. Keep one encrypted copy (KeePassXC or a USB stick) and delete the rest. A lost key only means a new key id and a release.

---

## 7. Workflows

| Repo › workflow | Trigger | Environment | What it does | Status |
|---|---|---|---|---|
| automation-maker › **CI** | push to `main`, PR (docs-only changes skipped) | `catalog` only in *publish catalog*, only on `main` | PR: Linux tests, packs, web, Worker. `main`: also the Windows test, four Windows app builds, custom package, Runner, then signs and uploads the catalog. Windows checks for PRs run locally first (CLAUDE.md, local-first) | ✅ green |
| automation-maker › **Release** | by hand, `main` | `catalog` | Signs the free set, builds the Runner and the Inno Setup installer, installs/uninstalls it on Windows, uploads `app/<version>/` and `app/latest.json` | ✅ 1.0.0 published 2026-10-18 |
| automation-maker › **Deploy download Worker** | by hand, `main` | `worker` | Worker tests, `wrangler deploy`, sets its secret | ✅ ran 2026-10-18 |
| automation-maker › **Sync automation-builds** | by hand, tag `engine-v*` | `sync` | Copies `engine/ spec/ tools/ build/`, `build.yml`, `CLAUDE.md` to automation-builds `main` | ✅ first run 2026-10-18 (`main` at b83c50f) |
| automation-maker › **Clean old artifacts** | by hand | none | Deletes old Actions artifacts (500 MB limit) | ✅ when needed |
| automation-builds › **Build** | by the API (`workflow_dispatch` on `main`) | none in the build job; `publish` in the publish job | Builds and checks one custom app from `jobs/<id>/`, then signs and uploads it | ⚠️ on `main` since the first Sync; not run yet (needs the routines and `publish` secrets) |

---

## 8. What's in R2 (`makemyexe-builds`)

| Prefix | Holds | Written by | Kept |
|---|---|---|---|
| `catalog/manifest.json` | Index of published apps (the API reads it, 5-min cache) | *publish catalog* | Always |
| `catalog/<id>/<version>/` | Per-app zip + `Guide.pdf` (internal testing) | *publish catalog* | Latest 2 versions, delete older by hand |
| `runner/<version>/` | Runner zip blocks (~44 MB), shared by all apps | *publish catalog* | **Never** a lifecycle rule: every download needs it |
| `packs/catalog/<id>/<version>/` | Signed catalog packs (KB) | *publish catalog* | Latest 2 |
| `packs/jobs/…`, `jobs/…` | Custom apps | automation-builds *publish* | Lifecycle: delete after 14 days (rule `job-packs-14d`, `jobs-14d`) |
| `app/<version>/`, `app/latest.json` | Installer + pointer | *Release* | Latest 2, by hand; no lifecycle rule |
| `layers/<dist>/<version>/` 🔜 | Library layers | `layers` builds | Phase 2c |

Staying inside the free 10 GB: DEPLOY.md §10.

---

## 9. Known gaps (found 2026-10-18)

1. **No branch protection on automation-builds `main`.** Rulesets on private repos need GitHub Pro (the API answers "Upgrade to GitHub Pro"). DEPLOY.md §5 step 3 assumes a ruleset. Until there's one, what keeps a routine off `main` is the routine's own push setting (Claude Code pushes only `claude/` branches unless unrestricted pushes are enabled; keep that off) and the sync token being the only other writer. Options before routines go live: GitHub Pro ($4/month), or keep the routine restricted and add a check in *Build* that refuses to run if `main`'s last commit isn't from *Sync*.
2. **Environment branch rules on a Free private repo:** they're accepted and saved, but we haven't yet proven they're enforced. Test once with a throwaway branch whose job names `publish` and only reports whether the secret is empty, then delete the branch.
3. `publish` has only `PACK_SIGNING_KEY`: custom apps can't be uploaded until `R2_*`, `BUILD_CALLBACK_SECRET` and `API_BASE_URL` are added (DEPLOY.md §5 step 6).
4. R2 lifecycle rules and a Cloudflare budget alert: confirm they exist (DEPLOY.md §10).

---

## 10. Tools

| Where | Tool | Why |
|---|---|---|
| Your PC | Git Bash, `gh`, `openssl`, Python 3.12 + `uv`, Node 22 | Repo work, key generation (`openssl genpkey -algorithm ed25519`), local runs |
| CI (Windows) | PyInstaller (`--onedir`), Inno Setup | Freeze the Runner once per release; per-user installer (no admin) |
| CI (Linux) | `openssl pkeyutl` | Ed25519 signing of packs in the publish jobs |
| CI | `wrangler@4` | Worker deploy |
| Checks | Ruff, pytest, Bandit, pip-audit, `tools/check_job` | Same gates for our code and generated code (ARCHITECTURE.md §9) |
| Later | KeePassXC | Encrypted backup of the `.pem` keys |
