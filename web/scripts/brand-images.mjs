// Render public/og-image.png (link previews) and public/apple-touch-icon.png from public/favicon.svg.
//   node scripts/brand-images.mjs      (needs Chromium at /opt/pw-browsers/chromium or CHROMIUM_PATH)
import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const publicDir = fileURLToPath(new URL("../public", import.meta.url));
const logo = await readFile(join(publicDir, "favicon.svg"), "utf8");
const logoUrl = `data:image/svg+xml;base64,${Buffer.from(logo).toString("base64")}`;

const og = `<html><body style="margin:0;width:1200px;height:630px;font-family:'Segoe UI',Inter,'DejaVu Sans',sans-serif;
  background:linear-gradient(135deg,#eef2ff 0%,#ffffff 55%,#e0e7ff 100%);display:flex;flex-direction:column;justify-content:center;padding:0 96px;box-sizing:border-box;color:#0f172a">
  <div style="display:flex;align-items:center;gap:20px">
    <img src="${logoUrl}" style="width:72px;height:72px">
    <span style="font-size:44px;font-weight:700;letter-spacing:-1px">MakeMy<span style="color:#4f46e5">EXE</span></span>
  </div>
  <div style="margin-top:48px;font-size:64px;font-weight:700;line-height:1.1;letter-spacing:-1.5px;max-width:960px">
    Everyday office work, done by <span style="color:#4f46e5">your own Windows app</span></div>
  <div style="margin-top:32px;font-size:30px;color:#475569">Runs offline · Your files never leave your PC · Guide included</div>
</body></html>`;

const browser = await chromium.launch({ executablePath: process.env.CHROMIUM_PATH || "/opt/pw-browsers/chromium" });
try {
  const page = await browser.newPage({ viewport: { width: 1200, height: 630 } });
  await page.setContent(og);
  await page.screenshot({ path: join(publicDir, "og-image.png") });
  await page.setViewportSize({ width: 180, height: 180 });
  await page.setContent(`<html><body style="margin:0"><img src="${logoUrl}" style="width:180px;height:180px;display:block"></body></html>`);
  await page.screenshot({ path: join(publicDir, "apple-touch-icon.png"), omitBackground: true });
} finally {
  await browser.close();
}
console.log("saved public/og-image.png and public/apple-touch-icon.png");
