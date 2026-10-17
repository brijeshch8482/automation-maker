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
2. **Login settings.** People can sign in three ways: **email + password**, a **6-digit code by email**, or **Google**. All three end in the same Supabase login, so the API needs nothing extra.
   - Authentication › **Sign In / Providers › Email**: enabled, **Confirm email** on, **Minimum password length** `8`.
   - Authentication › **URL Configuration**:
     - **Site URL:** your Pages URL, e.g. `https://makemyexe.pages.dev`
     - **Redirect URLs** (add each one):
       - `https://makemyexe.pages.dev/**`
       - `https://*.makemyexe.pages.dev/**` (Cloudflare preview deployments)
       - `http://localhost:5173/**` (local development)

     Google and the links in emails send people back to the site (to `/login` and the site root), so the site must be listed or Supabase refuses the redirect.
   - Authentication › **Emails › Templates**: put the code into three templates so people can type it instead of clicking (the link keeps working too). Keep the subject lines; replace the body's main line:
     - **Magic Link** (sign-in code): `Your MakeMyEXE sign-in code is <strong>{{ .Token }}</strong>. It expires in 1 hour. Or <a href="{{ .ConfirmationURL }}">sign in with this link</a>.`
     - **Confirm signup**: `Your MakeMyEXE confirmation code is <strong>{{ .Token }}</strong>. Or <a href="{{ .ConfirmationURL }}">confirm with this link</a>.`
     - **Reset Password**: `Your MakeMyEXE password reset code is <strong>{{ .Token }}</strong>. Or <a href="{{ .ConfirmationURL }}">reset it with this link</a>.`

     The site asks for a 6-digit code. If Authentication › Sign In / Providers › Email shows an **Email OTP Length**, keep it at `6`.
   - **Email delivery.** Supabase's built-in mailer sends only a few emails per hour and is meant for testing. Before real users arrive, set Authentication › **Emails › SMTP Settings** to a mail service (Resend, Brevo and Amazon SES have free tiers) with a sender like `MakeMyEXE <no-reply@your-domain>`. The SMTP password goes only into that Supabase field.
   - **Google.** The "Continue with Google" button appears on the site by itself as soon as Google is switched on in Supabase.
     1. [console.cloud.google.com](https://console.cloud.google.com) › create a project `MakeMyEXE`.
     2. **Google Auth Platform › Branding** (OAuth consent screen): app name `MakeMyEXE`, your support email, logo (`web/public/apple-touch-icon.png`), app home page = your site, privacy policy = `<site>/privacy`, terms = `<site>/terms`, authorised domain `supabase.co` plus your site's domain. Audience: **External**, then **Publish app** so anyone can sign in.
     3. **Clients › Create client** › Web application, name `MakeMyEXE web`. **Authorised JavaScript origins:** your site URL. **Authorised redirect URIs:** `https://<ref>.supabase.co/auth/v1/callback` (Supabase shows this exact URL on its Google provider page).
     4. Copy the **Client ID** and **Client secret** into Supabase › Authentication › Sign In / Providers › **Google**, and enable it. The secret goes only into that Supabase field.
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

> **GitHub secrets live in environments, never in repository secrets.** A repository secret reaches every workflow on every branch; an environment secret reaches only jobs that name the environment, and only from the branches you allow. Always **create the environment with its branch rule first, then add the secrets inside it**. Never skip ahead: a workflow job that names an environment that doesn't exist yet creates it on its own, with **no** branch rule, and anything you add there later is unprotected. If that ever happens, open the environment and set the rule before adding anything.
>
> To create one: repo › Settings › Environments › **New environment** › name it › *Deployment branches and tags* › **Selected branches and tags** › *Add deployment branch or tag rule* for each entry in the table › Save. Then, on the same page, *Environment secrets* › **Add environment secret** (and *Environment variables* for variables).
>
> | Repo | Environment | Allowed branches and tags | Holds |
> |---|---|---|---|
> | automation-maker | `sync` | branch `main`, tag `engine-v*` | `BUILDS_SYNC_TOKEN` (step 1) |
> | automation-maker | `catalog` | branch `main` | `R2_*` upload token (section 6, step 2) |
> | automation-builds | `publish` | branch `main` | `R2_*` upload token, `BUILD_CALLBACK_SECRET`, variable `API_BASE_URL` (step 6) |
>
> Settings › Secrets and variables › Actions › *Repository secrets* stays empty in both repos.

1. **Sync token.** GitHub › your avatar › Settings › Developer settings › Fine-grained tokens › Generate new token. Repository access: **only `automation-builds`**. Permissions: **Contents: Read and write** and **Workflows: Read and write** (the sync pushes `.github/workflows/build.yml`). First create the **`sync` environment** in automation-maker (Settings › Environments › New environment `sync` › Selected branches and tags › add branch rule `main` and tag rule `engine-v*` › Save). Then add the token there as environment secret `BUILDS_SYNC_TOKEN`, not as a repository secret.
2. **First sync.** automation-maker › Actions › *Sync automation-builds* › Run workflow (branch `main`). automation-builds `main` now has `engine/`, `spec/`, `tools/`, `build/`, `.github/workflows/build.yml` and `ENGINE_VERSION`. Later syncs run by themselves when you push a tag like `engine-v0.2.0`.
3. **Protect `main`.** automation-builds › Settings › Rules › Rulesets › New branch ruleset for `main`: restrict updates and deletions, block force pushes. Only the sync token (you) may push it; the `am-build` routine only pushes `claude/job-*` branches.
4. **Try a build before hosting exists.** In automation-builds create a branch `claude/job-test1` with a folder `jobs/test1/` that holds a copy of `automations/make-pdf/spec.json` and its `samples/` folder. Then Actions › *Build* › Run workflow with job id `test1`, branch `claude/job-test1`, attempt `0`. Without the settings below, the run only builds and checks: download `MakePDF.zip` and `Guide.pdf` from the run page (kept 7 days).
5. **R2 (private file storage, 10 GB free).** Cloudflare › R2 › Create bucket `makemyexe-builds`; leave public access off. R2 › Manage API tokens › Create API token: **Object Read & Write**, applied to that bucket only. Note the Access Key ID, the Secret Access Key and your Account ID (on the R2 overview page).
6. **Settings in automation-builds.** First create the **`publish` environment**: automation-builds › Settings › Environments › New environment `publish` › Selected branches and tags › add branch rule `main` › Save. Then add these on that environment's page (environment secrets and environment variables), never under repository secrets:

   | Name | Kind | Value |
   |---|---|---|
   | `BUILD_CALLBACK_SECRET` | secret | the **same** value as in Render |
   | `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | secrets | from step 5 |
   | `R2_BUCKET` | secret | `makemyexe-builds` |
   | `API_BASE_URL` | variable | `https://makemyexe-api.onrender.com` |

   Set all of them or none: a half-configured publish step fails on purpose. The build job, where generated code runs, can't see any of them: only the publish job names the environment.
7. **Let the API start builds.** GitHub › Fine-grained tokens › a second token, only `automation-builds`, **Actions: Read and write**. Put it into Render as `BUILDS_GITHUB_TOKEN`.

## 6. Downloads (Cloudflare R2)

Finished apps live in a **private** R2 bucket. Nobody gets a public link to it: the API hands out signed links that work for 15 minutes. Two tokens keep the roles apart, and each secret goes only into the dashboard named here:

1. **Bucket.** If you didn't make it in section 5: Cloudflare › R2 › Create bucket `makemyexe-builds`, public access **off**. R2 is free up to 10 GB of storage, and downloads from it cost nothing.
2. **Upload token** (GitHub Actions only). R2 › Manage API tokens › Create API token `makemyexe-publish`: **Object Read & Write**, that bucket only. First create the **`catalog` environment** in automation-maker (Settings › Environments › New environment `catalog` › Selected branches and tags › add branch rule `main` › Save). Then add four environment secrets there, never as repository secrets: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` (`makemyexe-builds`). The same four values go into the automation-builds `publish` environment (section 5, step 6).
3. **Read-only token** (the API only). Create a second token `makemyexe-api`: **Object Read only**, that bucket only. Put its values into **Render** › the API service › Environment: `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`. The API can then sign download links, but can never change or delete a file.
4. **First release.** CI publishes the catalog on every push to `main` (job *publish catalog*, after the tests and the four Windows builds pass): `catalog/<id>/<version>/<App>.zip`, `Guide.pdf`, and last `catalog/manifest.json`. After adding the secrets to the `catalog` environment, open the latest CI run on `main` › **Re-run all jobs**, or merge the next PR.
5. **Check.** Open the site › any automation. Within five minutes of a release the button shows the size and version, for example "51 MB · version 1.0.0". Click it: the zip downloads, and the page shows the three steps to start the app. A custom app that finished building shows the same buttons on its page.

## 7. Custom apps (Claude routines)

A custom app is designed by the **am-spec** routine and built by **am-build**, both Claude Code routines on your Claude subscription, working in automation-builds. The exact prompts and payloads are in [ROUTINES.md](ROUTINES.md). Do sections 5 and 6 first. Tokens from these steps go only into Render; never paste them into a chat or a file.

1. **Sync automation-builds again.** automation-maker › Actions › *Sync automation-builds* › Run workflow (`main`). This brings `CLAUDE.md`, `docs/SPEC_GUIDE.md`, `examples/` and `tools/check_job` to automation-builds, which the routines read.
2. **Cloud environment.** claude.ai/code › environment menu › Add environment `am-builder`:
   - **Network access:** Custom › tick *Also include default list of common package managers* › add `makemyexe-api.onrender.com`.
   - **Setup script:** the three lines in [ROUTINES.md §1](ROUTINES.md) (`uv sync ...`).
   - **Environment variables:** none.
3. **Routine `am-spec`.** claude.ai/code/routines › New routine:
   - Name `am-spec`, repository **automation-builds** only, environment `am-builder`, **remove every connector**.
   - Prompt: copy the `am-spec` block from [ROUTINES.md §3](ROUTINES.md) exactly.
   - Trigger: Add another trigger › **API** › copy the URL › **Generate token** and copy it.
   - Put them into **Render** › Environment as `ROUTINE_SPEC_URL` and `ROUTINE_SPEC_TOKEN`.
4. **Routine `am-build`.** The same with the `am-build` prompt. Its URL and token go into Render as `ROUTINE_BUILD_URL` and `ROUTINE_BUILD_TOKEN`.
5. **Only job branches.** automation-builds › Settings › Rules › Rulesets: the `main` ruleset from section 5 step 3 must exist, so a routine can push only `claude/job-*` branches.
6. **Check the Render settings** before switching on:
   - `CALLBACK_TOKEN_SECRET`: random, 32+ characters;
   - `BUILD_CALLBACK_SECRET`: the same value as in the automation-builds `publish` environment;
   - `BUILDS_GITHUB_TOKEN`: from section 5 step 7.

   The API refuses to start in routine mode with a missing routine URL or a development secret, so a typo shows up at once in the Render logs.
7. **Switch on.** Render › Environment › `PROVIDER` = `routine` › Save (Render redeploys).
8. **Try it.** On the website, sign in › *Make a custom app* › describe a small task, for example "Count the words and lines in a text file and save a short report". The design appears in a few minutes, with a link to the routine session. Confirm it: the build takes 10–15 minutes, then the page shows **Download**. The same run from a terminal is in [ROUTINES.md §6](ROUTINES.md).

If a job fails, its page shows why, and each attempt links to its routine session and Windows run. Limits while routines are in research preview: 30 runs an hour per routine, and every run counts toward your Claude plan's usage.

## 8. Check the whole thing

1. Open `https://makemyexe.pages.dev`. The catalog shows at once (it ships with the site). On an automation page the Download button may say "Waking up our server" for up to a minute if the API was asleep.
2. **Sign in, all three ways:**
   - **Create an account** with email + password › type the code from the confirmation email › you land on My apps.
   - Sign out (the round account button, top right) › **Email code** tab › type the code you receive.
   - Sign out › **Continue with Google** › pick your account › you come back to the site, signed in.
   - **Forgot password?** › code › new password.
3. **Submit a description.** With `PROVIDER=fake` no routine runs, so the job stays in "Designing" until the watchdog fails it after 15 minutes. That's expected until the routines are set up (section 7).
4. **Rotating a secret:** change it in the dashboard and redeploy. For `BUILD_CALLBACK_SECRET`, update automation-builds at the same time.

## 9. Pack signing keys (Runner + packs, Phase 2b)

Apps are delivered as signed packs, and the Runner runs only packs signed with a key it trusts. There are two keys: **catalog** (ready-made apps, automation-maker) and **jobs** (custom apps, automation-builds). Nothing needs them until packs are published (Phase 2b part 2), but they can be made now. The private halves go only into GitHub environments, never into the repo or a chat. The public halves are public: they go into `build/trusted_keys.json`.

1. **Make the key pairs** on your own computer (Git Bash on Windows, or a terminal on Mac/Linux; needs `openssl`):
   ```bash
   openssl genpkey -algorithm ed25519 -out catalog-1.pem
   openssl genpkey -algorithm ed25519 -out jobs-1.pem
   for k in catalog-1 jobs-1; do echo "$k: $(openssl pkey -in $k.pem -pubout -outform DER | tail -c 32 | od -An -tx1 | tr -d ' \n')"; done
   ```
   The last line prints each public key as 64 hex characters. With a checkout of this repo, `uv run python -m build.pack keygen --key-id catalog-1 --out keys/` does the same.
2. **Private halves into the environments** (create each environment with its branch rule first, §5):
   - automation-maker › environment `catalog` › secret `PACK_SIGNING_KEY` = the whole contents of `catalog-1.pem`, from `-----BEGIN PRIVATE KEY-----` through `-----END PRIVATE KEY-----`;
   - automation-builds › environment `publish` › secret `PACK_SIGNING_KEY` = the contents of `jobs-1.pem`.
3. **Public halves into the repo:** add `"catalog-1": "<hex>"` and `"jobs-1": "<hex>"` to `build/trusted_keys.json` in a PR, or send me the two hex lines: they're public, so they may be shared.
4. **Delete the `.pem` files** from your computer, or keep them offline (on a USB stick, say) in case you need them. A lost key just means a new key id (`catalog-2`) and a Runner release.

## Running the API image locally

```bash
docker build -f api/Dockerfile -t makemyexe-api .
docker run --rm -p 8000:8000 -e DATABASE_URL=sqlite+aiosqlite:////tmp/dev.db makemyexe-api
curl localhost:8000/health
```
Behind a TLS-inspecting proxy, add `--secret id=ca_bundle,src=/path/to/proxy-ca.crt` to the build.
