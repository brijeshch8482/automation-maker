# Deploying MakeMyEXE on the free plan

Internal phase hosting from [ARCHITECTURE.md §6.1](ARCHITECTURE.md): **Supabase** (Postgres + login), **Render** (the API, Docker), **Cloudflare Pages** (the website) and **cron-job.org** (keeps the API awake). Everything here costs ₹0.

> **Secrets go only into the Supabase, Render and Cloudflare dashboards.** Never commit them, never put them in a file in this repo, and never paste them into a chat (including with Claude). If one leaks, rotate it in the dashboard it came from.

Do the steps in this order; later steps need values from earlier ones.

| Thing | Where its value comes from | Goes into |
|---|---|---|
| Project URL `https://<ref>.supabase.co` | Supabase › Project Settings › API | Render `SUPABASE_URL`, Cloudflare `VITE_SUPABASE_URL` |
| Publishable key `sb_publishable_…` | Supabase › Project Settings › API Keys | Cloudflare `VITE_SUPABASE_ANON_KEY` |
| Session pooler connection string | Supabase › **Connect** › Session pooler | Render `DATABASE_URL` |
| API URL `https://makemyexe-api.onrender.com` | Render, after the first deploy | Render `PUBLIC_BASE_URL`, Cloudflare `VITE_API_URL`, cron-job.org |
| Site URL `https://makemyexe.pages.dev` | Cloudflare Pages, after the first deploy | Render `CORS_ORIGINS`, Supabase Auth URL configuration |

---

## 1. Supabase (database + login)

1. **Create the project.** [supabase.com/dashboard](https://supabase.com/dashboard) › New project.
   - Name: `makemyexe`.
   - **Region: South Asia (Mumbai)** (`ap-south-1`). It's closest to users, and Render's Singapore region is the nearest to it.
   - Database password: let Supabase generate a strong one and save it in your password manager. You need it once, in step 3.
2. **Login settings.** Authentication › Sign In / Providers: keep **Email** enabled. We use the magic link, so no password is needed.
   - Authentication › **URL Configuration**:
     - **Site URL:** `https://makemyexe.pages.dev`
     - **Redirect URLs** (add each one):
       - `https://makemyexe.pages.dev`
       - `https://*.makemyexe.pages.dev` (Cloudflare preview deployments)
       - `http://localhost:5173` (local development)

   The website asks Supabase to send people back to the site root after they click the email link, so the root URLs above must be listed or the link is refused.
3. **Connection string for the API.** Click **Connect** (top of the project page) › **Session pooler** › copy the URI. It looks like:
   ```
   postgresql://postgres.<ref>:[YOUR-PASSWORD]@aws-0-ap-south-1.pooler.supabase.com:5432/postgres
   ```
   - Use the **Session pooler**. The "Direct connection" is IPv6-only on the free plan, and Render can't reach it. The Transaction pooler (port 6543) also works, but isn't needed.
   - Replace `[YOUR-PASSWORD]` with the database password. If it contains `@ : / ? # [ ] %`, URL-encode those characters (for example `@` → `%40`).
   - Keep it for Render's `DATABASE_URL`. Copy it straight into the Render dashboard, not into a file.
   - The API converts this URL for its driver and **requires SSL** by itself, so there's nothing to add to it.
4. **Keys for the website.** Project Settings › **API Keys**: copy the **Publishable key** (`sb_publishable_…`). It's safe in a browser, and it goes into Cloudflare.
   - **Never use the secret key** (`sb_secret_…`, or the legacy `service_role`) anywhere in this project.
   - Project Settings › **JWT Keys**: new projects sign logins with asymmetric keys, and the API checks them through the project's public key list (JWKS). Nothing to copy.
   - Only if your project still uses the **legacy JWT secret**: copy it into Render's `SUPABASE_JWT_SECRET`.
5. **Tables:** don't create any. The API creates them on its first start (Alembic migrations) and turns on **Row Level Security**. Without RLS, Supabase's public Data API would let anyone holding the publishable key read every job. The API itself connects as the table owner and is not affected.
6. **Free-plan note:** a project with no database activity for about a week is **paused**. Resume it from the dashboard. The cron ping in step 4 counts as activity only if a request touches the database, so you may still need to resume it after quiet weeks.

## 2. Render (the API)

1. [dashboard.render.com](https://dashboard.render.com) › **New › Blueprint** › connect GitHub and pick the `automation-maker` repository (branch `main`). Render reads [`render.yaml`](../render.yaml): one **free** Docker web service named `makemyexe-api`, in the **Singapore** region, health check `/health`. It only rebuilds when `api/`, `spec/`, `automations/`, `pyproject.toml` or `uv.lock` change.
2. Render asks for each `sync: false` variable. Fill in the **required** ones. Leave the optional ones **blank**: blank means "use the default".

   | Variable | Value | Where it comes from |
   |---|---|---|
   | `DATABASE_URL` | the Session pooler URI | Supabase step 3 |
   | `SUPABASE_URL` | `https://<ref>.supabase.co` | Supabase › Project Settings › API |
   | `PUBLIC_BASE_URL` | `https://makemyexe-api.onrender.com` | the service URL; routines call back to it |
   | `CORS_ORIGINS` | `https://makemyexe.pages.dev` | your Pages URL (comma-separate several, e.g. a custom domain) |
   | `CALLBACK_TOKEN_SECRET` | 64 random hex characters | generate it yourself (below) |
   | `BUILD_CALLBACK_SECRET` | 64 random hex characters | generate it; later the **same** value goes into automation-builds |
   | `PROVIDER` | `fake` (already set) | change to `routine` once the routines exist ([ROUTINES.md](ROUTINES.md)) |
   | `DEV_AUTH` | `false` (already set) | never `true` on Render |
   | `ROUTINE_SPEC_URL`, `ROUTINE_SPEC_TOKEN`, `ROUTINE_BUILD_URL`, `ROUTINE_BUILD_TOKEN` | blank for now | claude.ai/code/routines › each routine › API trigger ([ROUTINES.md §1](ROUTINES.md)) |
   | `BUILDS_GITHUB_TOKEN` | blank for now | GitHub › fine-grained token, **Actions: write on automation-builds only** |
   | `BUILDS_REPO`, `BUILDS_WORKFLOW` | blank | defaults `brijeshch8482/automation-builds` and `build.yml` |
   | `SUPABASE_JWT_SECRET` | blank | only for a legacy-JWT Supabase project |
   | `SUPABASE_JWT_AUDIENCE`, `CATALOG_DIR`, `SPEC_TIMEOUT_MIN`, `GENERATION_TIMEOUT_MIN`, `BUILD_TIMEOUT_MIN`, `WATCHDOG_INTERVAL_S`, `MAX_REPAIRS`, `UNCONFIRMED_EXPIRY_DAYS`, `DESCRIPTION_RETENTION_DAYS` | blank | defaults in `api/src/api/config.py` |

   To generate a secret, run this **on your own computer** and paste the output straight into the Render field:
   ```
   python3 -c "import secrets; print(secrets.token_hex(32))"
   ```
3. **Apply.** The first build takes a few minutes. On every start the container runs `python -m api.migrate` and then uvicorn. Render's pre-deploy command needs a paid plan, so migrations run at start-up; they do nothing when the schema is current.
   - **Startup checks:** the API **refuses to start** on Render if `DATABASE_URL` isn't Postgres, if either callback secret is missing or still the dev default, or if `DEV_AUTH` is on. The deploy log names exactly which one.
4. **Check it:** open `https://makemyexe-api.onrender.com/health` (it should return `{"status":"ok"}`) and `/automations` (it should list the Invoice Generator).
   - If Render gave the service a different URL (for example a suffix because the name was taken), use that URL everywhere this guide says `makemyexe-api.onrender.com`, and update `PUBLIC_BASE_URL`.
5. **Free-plan facts:**
   - The service sleeps after 15 minutes without traffic; the cron ping in step 4 prevents that.
   - The free plan gives 750 instance hours a month, so this must be the **only** free web service on the Render account.
   - 512 MB RAM, one worker.

## 3. Cloudflare Pages (the website)

1. [dash.cloudflare.com](https://dash.cloudflare.com) › **Workers & Pages › Create › Pages › Connect to Git**, then pick `automation-maker`. Project name: `makemyexe` (that gives `https://makemyexe.pages.dev`).
2. **Build settings:**

   | Setting | Value |
   |---|---|
   | Production branch | `main` |
   | Framework preset | None |
   | Root directory | `web` |
   | Build command | `npm run build` |
   | Build output directory | `dist` |

   Pages installs dependencies from `web/package-lock.json` itself. The build reads `automations/*/spec.json` from the repo root, which works because Pages checks out the whole repository.
3. **Environment variables** (Settings › Variables and Secrets; set them for **Production** and **Preview**):

   | Variable | Value |
   |---|---|
   | `NODE_VERSION` | `22` |
   | `VITE_API_URL` | `https://makemyexe-api.onrender.com` |
   | `VITE_SUPABASE_URL` | `https://<ref>.supabase.co` |
   | `VITE_SUPABASE_ANON_KEY` | the **publishable key** `sb_publishable_…` (the name predates the new key format) |
   | `VITE_CONTACT_EMAIL` | optional: a public address for the footer, Privacy and Terms pages (e.g. a support mailbox, not a personal one) |

   - **Don't set `VITE_DEV_AUTH`** on Pages.
   - `VITE_` variables are baked into the public JavaScript, so only ever put browser-safe values here: the publishable key yes, the secret key never.
   - After changing a variable, **redeploy** (Deployments › Retry deployment), because the values are read at build time.
4. `web/public/_redirects` sends every path to `index.html`, so links like `/jobs/job_…` work when opened directly or reloaded.
5. If you add a custom domain later, add it to Render's `CORS_ORIGINS` and to Supabase's URL configuration too.

## 4. cron-job.org (keep the API awake)

1. Create a free account at [cron-job.org](https://cron-job.org), then **Create cronjob**:
   - URL: `https://makemyexe-api.onrender.com/health`
   - Schedule: **every 10 minutes**
   - Request method: GET
   - Notifications: on failure, to your email.
2. That's about 744 hours a month of uptime, inside Render's 750 free hours. The job watchdog runs inside the API, so it only works while the API is awake.
3. Don't use a GitHub Actions cron for this: its per-run minute rounding would use up the free Actions minutes.

## 5. automation-builds (Windows builds)

The Windows workflow lives in the `automation-builds` repo. Its `main` is a copy of `engine/ spec/ tools/ build/` made by the **Sync automation-builds** workflow; never edit it by hand. Secrets for this part go only into the GitHub settings pages named below.

1. **Sync token.** GitHub › your avatar › Settings › Developer settings › Fine-grained tokens › Generate new token. Repository access: **only `automation-builds`**. Permissions: **Contents: Read and write** and **Workflows: Read and write** (the sync pushes `.github/workflows/build.yml`). Copy the token into **automation-maker** › Settings › Secrets and variables › Actions › New repository secret `BUILDS_SYNC_TOKEN`.
2. **First sync.** automation-maker › Actions › *Sync automation-builds* › Run workflow (branch `main`). automation-builds `main` now has `engine/`, `spec/`, `tools/`, `build/`, `.github/workflows/build.yml` and `ENGINE_VERSION`. Later syncs run by themselves when you push a tag like `engine-v0.2.0`.
3. **Protect `main`.** automation-builds › Settings › Rules › Rulesets › New branch ruleset for `main`: restrict updates and deletions, block force pushes. Only the sync token (you) may push it; the `am-build` routine only pushes `claude/job-*` branches.
4. **Try a build before hosting exists.** In automation-builds create a branch `claude/job-test1` with a folder `jobs/test1/` that holds a copy of `automations/make-pdf/spec.json` and its `samples/` folder. Then Actions › *Build* › Run workflow with job id `test1`, branch `claude/job-test1`, attempt `0`. Without the settings below, the run only builds and checks: download `MakePDF.zip` and `Guide.pdf` from the run page (kept 7 days).
5. **R2 (private file storage, 10 GB free).** Cloudflare › R2 › Create bucket `makemyexe-builds`; leave public access off. R2 › Manage API tokens › Create API token: **Object Read & Write**, applied to that bucket only. Note the Access Key ID, the Secret Access Key and your Account ID (on the R2 overview page).
6. **Settings in automation-builds** › Settings › Secrets and variables › Actions:

   | Name | Kind | Value |
   |---|---|---|
   | `BUILD_CALLBACK_SECRET` | secret | the **same** value as in Render |
   | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | secrets | from step 5 |
   | `R2_BUCKET` | secret | `makemyexe-builds` |
   | `API_BASE_URL` | variable | `https://makemyexe-api.onrender.com` |

   Set all of them or none: a half-configured publish step fails on purpose.
7. **Let the API start builds.** GitHub › Fine-grained tokens › a second token, only `automation-builds`, **Actions: Read and write**. Put it into Render as `BUILDS_GITHUB_TOKEN`.

## 6. Check the whole thing

1. Open `https://makemyexe.pages.dev`. The catalog loads from the API (if the API is still waking up, the first load can take up to about 50 seconds).
2. **Sign in:** Make a custom one › Sign in to continue › enter your email › click the link in the email. You land back on the site, signed in.
3. **Submit a description.** With `PROVIDER=fake` no routine runs, so the job stays in "Designing" until the watchdog fails it after 15 minutes. That's expected until the routines are set up ([ROUTINES.md](ROUTINES.md)); then set `PROVIDER=routine` and fill in the `ROUTINE_*` variables.
4. **Rotating a secret:** change it in the dashboard and redeploy. For `BUILD_CALLBACK_SECRET`, update automation-builds at the same time.

## Running the API image locally

```bash
docker build -f api/Dockerfile -t makemyexe-api .
docker run --rm -p 8000:8000 -e DATABASE_URL=sqlite+aiosqlite:////tmp/dev.db makemyexe-api
curl localhost:8000/health
```
Behind a TLS-inspecting proxy, add `--secret id=ca_bundle,src=/path/to/proxy-ca.crt` to the build.
