// makemyexe-download: GET /d/<token> streams, merged from pre-built zip blocks in R2
// (docs/ARCHITECTURE.md §8.6), either <Name>.zip = Runner + layers + app pack (the per-app
// download for internal testing) or <Name>.mmx = a bundle for the installed app: the pack's
// bundle block (bundle.json + packs/<id>-<version>.mmx) + its layer blocks (docs/DESKTOP_APP.md
// §4, §11.2). Bound to the bucket (read only), it holds no R2 keys; the token from the API names
// exactly what goes in and expires in 15 min.

import { TokenError, verifyToken } from "./token.js";
import { LayoutError, planZip } from "./zip.js";

function text(status, body) {
  return new Response(body, {
    status,
    headers: { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" },
  });
}

const BUNDLE_ENTRY = /^(bundle\.json|packs\/[a-z0-9.-]+\.mmx)$/;
const LAYER_ENTRY = /^layers\/[A-Za-z0-9_.]+-[A-Za-z0-9_.+!]+\//;

async function layout(bucket, prefix, allow) {
  const object = await bucket.get(`${prefix}/layout.json`);
  if (!object) throw new LayoutError(`missing ${prefix}`);
  return { prefix, layout: await object.json(), allow };
}

async function stream(bucket, parts, writable) {
  const writer = writable.getWriter();
  try {
    for (const part of parts) {
      if (part instanceof Uint8Array) {
        await writer.write(part);
        continue;
      }
      const object = await bucket.get(part.key);
      if (!object || object.size !== part.size) throw new LayoutError(`size mismatch for ${part.key}`);
      const reader = object.body.getReader();
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        await writer.write(value); // bytes passed through untouched
      }
    }
    await writer.close();
  } catch (err) {
    await writer.abort(err);
  }
}

export async function handle(request, env, ctx) {
  const url = new URL(request.url);
  if (request.method !== "GET") return text(405, "Method not allowed");
  const match = url.pathname.match(/^\/d\/([A-Za-z0-9_.-]+)$/);
  if (!match) return text(404, "Not found");

  let payload;
  try {
    payload = await verifyToken(env.DOWNLOAD_TOKEN_SECRET, match[1]);
  } catch (err) {
    if (err instanceof TokenError && err.message === "expired") {
      return text(410, "This download link has expired. Go back to the app's page and click Download again.");
    }
    return text(403, "This download link is not valid.");
  }

  const bundle = payload.kind === "bundle";
  let plan;
  try {
    const blocks = [];
    if (bundle) {
      for (const prefix of payload.layers) blocks.push(await layout(env.BUCKET, `${prefix}/bundle`, LAYER_ENTRY));
      blocks.push(await layout(env.BUCKET, `${payload.pack}/bundle`, BUNDLE_ENTRY));
      plan = planZip(null, blocks);
    } else {
      const runner = await layout(env.BUCKET, payload.runner);
      for (const prefix of [...payload.layers, payload.pack]) blocks.push(await layout(env.BUCKET, prefix));
      plan = planZip(runner, blocks, `${payload.name}.exe`);
    }
  } catch (err) {
    if (err instanceof LayoutError) return text(503, "This app is being updated. Try again in a few minutes.");
    throw err;
  }

  const Fixed = globalThis.FixedLengthStream;
  const { readable, writable } = Fixed ? new Fixed(plan.size) : new TransformStream();
  const done = stream(env.BUCKET, plan.parts, writable);
  if (ctx?.waitUntil) ctx.waitUntil(done);
  return new Response(readable, {
    headers: {
      "Content-Type": bundle ? "application/octet-stream" : "application/zip",
      "Content-Disposition": `attachment; filename="${payload.name}.${bundle ? "mmx" : "zip"}"`,
      "Content-Length": String(plan.size),
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    },
  });
}

export default { fetch: handle };
