// Render every page in headless Chromium and save PNGs to docs/screenshots/web/.
//
// 1. Static pages from the bundled catalog (no API).
// 2. The custom-job flow against the real FastAPI app (fake provider, dev login). This script
//    plays the routines and the Windows build by POSTing their callbacks, signed like the real ones.
//
//   npm run screenshots          (needs uv, and Chromium at /opt/pw-browsers/chromium or CHROMIUM_PATH)
import { spawn } from "node:child_process";
import { createHmac } from "node:crypto";
import { mkdir, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";
import { build, preview } from "vite";

const webDir = fileURLToPath(new URL("..", import.meta.url));
const repoRoot = fileURLToPath(new URL("../..", import.meta.url));
const outDir = join(repoRoot, "docs/screenshots/web");
const executablePath = process.env.CHROMIUM_PATH || "/opt/pw-browsers/chromium";

const SITE = "http://localhost:4321";
const API_PORT = 8766;
const API = `http://127.0.0.1:${API_PORT}`;
const CALLBACK_SECRET = "screenshots-callback-secret";
const BUILD_SECRET = "screenshots-build-secret";

const VIEWPORTS = { desktop: { width: 1280, height: 860 }, mobile: { width: 390, height: 844 } };

async function shot(page, name, device) {
  // Sticky elements are drawn where the viewport is; full-page shots start from the top.
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(250); // let colour transitions finish
  const file = join(outDir, `${name}-${device}.png`);
  await page.screenshot({ path: file, fullPage: true });
  console.log(`saved ${file}`);
}

// --- 1. Static pages ----------------------------------------------------------------------

const STATIC_SHOTS = [
  ["home", "/"],
  ["catalog", "/automations"],
  ["catalog-filtered", "/automations", (page) => page.getByRole("button", { name: "PDF", exact: true }).click()],
  ["invoice-generator", "/automations/invoice-generator"],
  [
    "invoice-generator-setup",
    "/automations/invoice-generator",
    (page) => page.getByRole("tab", { name: "Setup" }).click(),
  ],
  ["pdf-merge", "/automations/pdf-merge"],
  ["bulk-rename", "/automations/bulk-rename"],
  ["make-pdf", "/automations/make-pdf"],
  ["custom-empty", "/custom"],
  [
    "custom-pii-warning",
    "/custom",
    (page) =>
      page
        .getByLabel("What should it do?")
        .fill(
          "Make an invoice for Asha Traders, phone +91 98765 43210, GSTIN 27ABCPE1234F1Z5, " +
            "and email it to asha@example.com every month.",
        ),
  ],
  ["privacy", "/privacy"],
  ["terms", "/terms"],
  ["not-found", "/automations/nope"],
  // The menu button only exists at phone width.
  ["menu-open", "/", (page) => page.getByRole("button", { name: "Open menu" }).click(), ["mobile"]],
];

async function staticShots(browser) {
  await build({ root: webDir, logLevel: "warn", build: { outDir: "dist" } });
  const server = await preview({ root: webDir, preview: { port: 4321, strictPort: true }, logLevel: "warn" });
  try {
    for (const [device, viewport] of Object.entries(VIEWPORTS)) {
      const page = await browser.newPage({ viewport });
      for (const [name, path, action, devices] of STATIC_SHOTS) {
        if (devices && !devices.includes(device)) continue;
        await page.goto(`${SITE}${path}`, { waitUntil: "networkidle" });
        if (action) {
          await action(page);
          await page.waitForTimeout(400); // let colour transitions finish
        }
        await shot(page, name, device);
      }
      await page.close();
    }
  } finally {
    server.httpServer.close();
  }
}

// --- 2. Job flow against the real API -------------------------------------------------------

function callbackToken(jobId) {
  return createHmac("sha256", CALLBACK_SECRET)
    .update(`routine-callback:${jobId}`)
    .digest("base64url");
}

async function routineCallback(jobId, payload) {
  const res = await fetch(`${API}/internal/routine-callback`, {
    method: "POST",
    headers: { Authorization: `Bearer ${callbackToken(jobId)}`, "Content-Type": "application/json" },
    body: JSON.stringify({ job_id: jobId, ...payload }),
  });
  if (res.status !== 204) throw new Error(`routine callback: ${res.status} ${await res.text()}`);
}

async function buildCallback(payload) {
  const body = JSON.stringify(payload);
  const signature = "sha256=" + createHmac("sha256", BUILD_SECRET).update(body).digest("hex");
  const res = await fetch(`${API}/internal/build-callback`, {
    method: "POST",
    headers: { "X-Signature": signature, "Content-Type": "application/json" },
    body,
  });
  if (res.status !== 204) throw new Error(`build callback: ${res.status} ${await res.text()}`);
}

async function startApi() {
  const dbPath = join(tmpdir(), `makemyexe-screenshots-${process.pid}.db`);
  await rm(dbPath, { force: true });
  const api = spawn(
    "uv",
    ["run", "uvicorn", "api.app:create_app", "--factory", "--port", String(API_PORT), "--log-level", "warning"],
    {
      cwd: repoRoot,
      stdio: ["ignore", "inherit", "inherit"],
      env: {
        ...process.env,
        DATABASE_URL: `sqlite+aiosqlite:///${dbPath}`,
        PROVIDER: "fake",
        DEV_AUTH: "true",
        PUBLIC_BASE_URL: API,
        CORS_ORIGINS: JSON.stringify([SITE]),
        CALLBACK_TOKEN_SECRET: CALLBACK_SECRET,
        BUILD_CALLBACK_SECRET: BUILD_SECRET,
        BUILDS_GITHUB_TOKEN: "", // fake dispatcher
      },
    },
  );
  for (let i = 0; i < 60; i++) {
    try {
      if ((await fetch(`${API}/health`)).ok) return { api, dbPath };
    } catch {
      // not up yet
    }
    await new Promise((r) => setTimeout(r, 500));
  }
  api.kill();
  throw new Error("API did not start");
}

async function jobFlow(browser, device, viewport, spec) {
  const page = await browser.newPage({ viewport });
  const user = `${device}-user`;
  const jobIdFromUrl = () => page.url().split("/jobs/")[1];

  await page.goto(`${SITE}/login?next=/custom`, { waitUntil: "networkidle" });
  await shot(page, "login", device);
  await page.getByLabel("Dev user name").fill(user);
  await page.getByRole("button", { name: "Sign in" }).click();

  await page.getByLabel("What should it do?").fill(
    "I make GST invoices for customers: customer name and phone, a list of items with " +
      "quantity and rate, and GST. Save each invoice as a numbered PDF.",
  );
  await shot(page, "custom-signed-in", device);
  await page.getByRole("button", { name: "Design my automation" }).click();
  await page.getByText("Designing your automation").waitFor();
  const jobId = jobIdFromUrl();
  await shot(page, "job-designing", device);

  await routineCallback(jobId, {
    mode: "spec",
    revision: 0,
    status: "ok",
    spec,
    assumptions: [
      "Invoice numbers continue from the last one, starting at INV-1.",
      "GST is 18% unless you change it on each invoice.",
    ],
    questions: ["Do you need a discount column?", "Should invoices show your bank details?"],
  });
  await page.getByText("What we assumed").waitFor({ timeout: 10_000 });
  await shot(page, "job-review", device);

  // A change that breaks the steps: the server explains why it can't be saved.
  await page.getByRole("button", { name: "Remove Items" }).click();
  await page.getByRole("button", { name: "Save changes" }).click();
  await page.getByText("These changes can't be saved yet").waitFor();
  await shot(page, "job-review-invalid", device);
  await page.getByRole("button", { name: "Undo changes" }).click();

  await page.getByRole("button", { name: "Build my app" }).click();
  await page.getByText("Generating your app").waitFor();
  await shot(page, "job-generating", device);

  const branch = `claude/job-${jobId}`;
  await routineCallback(jobId, { mode: "build", attempt: 0, status: "ok", branch, commit_sha: "abc1234", used_custom_step: false });
  await buildCallback({
    job_id: jobId,
    attempt: 0,
    status: "failed",
    run_url: "https://github.com/brijeshch8482/automation-builds/actions/runs/1",
    report: { stage: "smoke_test", command: "app.exe --smoke-test sample_data.json", test: "test_invoice_total", log_tail: "AssertionError" },
  });
  await page.getByText("Fixing a problem found in the build").waitFor({ timeout: 10_000 });
  await shot(page, "job-repairing", device);

  await routineCallback(jobId, { mode: "repair", attempt: 1, status: "ok", branch, commit_sha: "def5678", used_custom_step: false });
  await buildCallback({
    job_id: jobId,
    attempt: 1,
    status: "passed",
    run_url: "https://github.com/brijeshch8482/automation-builds/actions/runs/2",
    artifact_key: `jobs/${jobId}/attempt-1/InvoiceGenerator.zip`,
    guide_key: `jobs/${jobId}/attempt-1/Guide.pdf`,
  });
  await page.reload({ waitUntil: "networkidle" });
  await page.getByText("Your app is ready").waitFor();
  await page.getByText("Details").click();
  await shot(page, "job-ready", device);

  // A second job whose design fails, for the failed state and the list.
  await page.goto(`${SITE}/custom`, { waitUntil: "networkidle" });
  await page.getByLabel("What should it do?").fill("Something vague about my files every week");
  await page.getByRole("button", { name: "Design my automation" }).click();
  await page.getByText("Designing your automation").waitFor();
  await routineCallback(jobIdFromUrl(), {
    mode: "spec",
    revision: 0,
    status: "failed",
    reason: "the description doesn't say what goes in or what should come out",
  });
  await page.getByText("We couldn't finish this one").waitFor({ timeout: 10_000 });
  await shot(page, "job-failed", device);

  await page.goto(`${SITE}/me/jobs`, { waitUntil: "networkidle" });
  await shot(page, "my-jobs", device);
  await page.close();
}

async function jobFlowShots(browser) {
  const spec = JSON.parse(await readFile(join(repoRoot, "automations/invoice-generator/spec.json"), "utf8"));
  const { api, dbPath } = await startApi();
  process.env.VITE_API_URL = API;
  process.env.VITE_DEV_AUTH = "true";
  try {
    await build({ root: webDir, logLevel: "warn", build: { outDir: "dist-e2e" } });
    const server = await preview({
      root: webDir,
      build: { outDir: "dist-e2e" },
      preview: { port: 4321, strictPort: true },
      logLevel: "warn",
    });
    try {
      for (const [device, viewport] of Object.entries(VIEWPORTS)) {
        await jobFlow(browser, device, viewport, spec);
      }
    } finally {
      server.httpServer.close();
    }
  } finally {
    delete process.env.VITE_API_URL;
    delete process.env.VITE_DEV_AUTH;
    api.kill();
    await rm(dbPath, { force: true });
  }
}

// --- 3. Sign-in screens (Supabase Auth, answered by this script) ---------------------------

const SUPABASE = "https://demo-project.supabase.co";

function fakeSession(email) {
  const now = Math.floor(Date.now() / 1000);
  return {
    access_token: "header.payload.signature",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: now + 3600,
    refresh_token: "refresh",
    user: { id: "user-1", email, aud: "authenticated", role: "authenticated", app_metadata: {}, user_metadata: {} },
  };
}

async function fakeSupabase(page) {
  await page.route(`${SUPABASE}/auth/v1/**`, (route) => {
    const path = new URL(route.request().url()).pathname.replace("/auth/v1", "");
    const body =
      path === "/settings"
        ? { external: { email: true, google: true }, disable_signup: false }
        : path === "/token"
          ? fakeSession("asha@example.com")
          : {};
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  const r2 = "https://acct.r2.cloudflarestorage.com/makemyexe-builds/catalog/make-pdf/1.0.0";
  await page.route(`${API}/**`, (route) => {
    const body = route.request().url().endsWith("/automations/make-pdf/download")
      ? {
          version: "1.0.0",
          filename: "MakePDF.zip",
          size_bytes: 51_200_000,
          url: `${r2}/MakePDF.zip?X-Amz-Signature=demo`,
          guide_url: `${r2}/Guide.pdf?X-Amz-Signature=demo`,
          expires_in: 900,
          built_at: "2026-10-17T11:00:00Z",
        }
      : [];
    return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
  });
  // The "download": R2 answers with an attachment, so the page stays where it is.
  await page.route("https://acct.r2.cloudflarestorage.com/**", (route) =>
    route.fulfill({
      status: 200,
      headers: { "Content-Type": "application/zip", "Content-Disposition": 'attachment; filename="MakePDF.zip"' },
      body: "PK",
    }),
  );
}

async function authShots(browser) {
  process.env.VITE_API_URL = API;
  process.env.VITE_SUPABASE_URL = SUPABASE;
  process.env.VITE_SUPABASE_ANON_KEY = "sb_publishable_demo";
  try {
    await build({ root: webDir, logLevel: "warn", build: { outDir: "dist-auth" } });
    const server = await preview({
      root: webDir,
      build: { outDir: "dist-auth" },
      preview: { port: 4321, strictPort: true },
      logLevel: "warn",
    });
    try {
      for (const [device, viewport] of Object.entries(VIEWPORTS)) {
        const page = await browser.newPage({ viewport });
        await fakeSupabase(page);
        const login = async () => {
          await page.goto(`${SITE}/login`, { waitUntil: "networkidle" });
          await page.getByRole("button", { name: "Continue with Google" }).waitFor();
        };
        await login();
        await shot(page, "auth-sign-in", device);
        await page.getByRole("tab", { name: "Email code" }).click();
        await page.getByLabel("Email").fill("asha@example.com");
        await shot(page, "auth-email-code", device);
        await page.getByRole("button", { name: "Email me a code" }).click();
        await page.getByLabel("Code").fill("123456");
        await shot(page, "auth-verify-code", device);

        await login();
        await page.getByRole("button", { name: "Create an account" }).click();
        await page.getByLabel("Email").fill("new@example.com");
        await page.getByLabel("Password", { exact: true }).fill("short");
        await shot(page, "auth-sign-up", device);

        await login();
        await page.getByRole("button", { name: "Forgot password?" }).click();
        await shot(page, "auth-forgot", device);

        await login();
        await page.getByLabel("Email").fill("asha@example.com");
        await page.getByLabel("Password", { exact: true }).fill("correct horse");
        await page.getByRole("button", { name: "Sign in", exact: true }).click();
        await page.getByRole("heading", { name: "My apps" }).waitFor();
        if (device === "desktop") {
          await page.getByRole("button", { name: "Account" }).click();
          await shot(page, "auth-account-menu", device);
        }

        await page.goto(`${SITE}/automations/make-pdf`, { waitUntil: "networkidle" });
        await page.getByText("51 MB · version 1.0.0").waitFor();
        await shot(page, "download-ready", device);
        await page.getByRole("button", { name: "Download for Windows" }).click();
        await page.getByText("Your download has started").waitFor();
        await shot(page, "download-started", device);
        await page.close();
      }
    } finally {
      server.httpServer.close();
    }
  } finally {
    delete process.env.VITE_API_URL;
    delete process.env.VITE_SUPABASE_URL;
    delete process.env.VITE_SUPABASE_ANON_KEY;
  }
}

await mkdir(outDir, { recursive: true });
const browser = await chromium.launch({ executablePath });
try {
  await staticShots(browser);
  await jobFlowShots(browser);
  await authShots(browser);
} finally {
  await browser.close();
}
