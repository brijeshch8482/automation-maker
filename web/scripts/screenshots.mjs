// Render every page of the built site in headless Chromium and save PNGs to
// docs/screenshots/web/. Run `npm run build` first.
//   CHROMIUM_PATH=/path/to/chrome npm run screenshots
import { mkdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";
import { preview } from "vite";

const outDir = fileURLToPath(new URL("../../docs/screenshots/web/", import.meta.url));
const executablePath = process.env.CHROMIUM_PATH || "/opt/pw-browsers/chromium";

const VIEWPORTS = { desktop: { width: 1280, height: 860 }, mobile: { width: 390, height: 844 } };

// [file name, path, optional page action before the shot]
const SHOTS = [
  ["catalog", "/"],
  ["invoice-generator", "/automations/invoice-generator"],
  [
    "invoice-generator-setup",
    "/automations/invoice-generator",
    (page) => page.getByRole("tab", { name: "Setup" }).click(),
  ],
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
  ["not-found", "/automations/nope"],
];

const server = await preview({ preview: { port: 4321, strictPort: true }, logLevel: "warn" });
const browser = await chromium.launch({ executablePath });
try {
  await mkdir(outDir, { recursive: true });
  for (const [device, viewport] of Object.entries(VIEWPORTS)) {
    const page = await browser.newPage({ viewport, deviceScaleFactor: 1 });
    for (const [name, path, action] of SHOTS) {
      await page.goto(`http://localhost:4321${path}`, { waitUntil: "networkidle" });
      if (action) await action(page);
      const file = `${outDir}${name}-${device}.png`;
      await page.screenshot({ path: file, fullPage: true });
      console.log(`saved ${file}`);
    }
    await page.close();
  }
} finally {
  await browser.close();
  server.httpServer.close();
}
