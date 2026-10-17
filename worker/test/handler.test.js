import assert from "node:assert/strict";
import { test } from "node:test";
import { handle } from "../src/index.js";
import { signToken } from "../src/token.js";

const empty = { get: async () => null };

async function call(path, env, method = "GET") {
  return handle(new Request(`https://dl.example${path}`, { method }), env, {});
}

test("refuses bad paths, methods and tokens without touching the bucket", async () => {
  const env = { BUCKET: empty, DOWNLOAD_TOKEN_SECRET: "s" };
  assert.equal((await call("/", env)).status, 404);
  assert.equal((await call("/d/x", env, "POST")).status, 405);
  assert.equal((await call("/d/abc.def", env)).status, 403);
  const expired = await signToken("s", {
    runner: "runner/1.0.0", layers: [], pack: "packs/catalog/a/1.0.0", name: "A", exp: 1,
  });
  assert.equal((await call(`/d/${expired}`, env)).status, 410);
});

test("a valid token for missing files is a clear 503", async () => {
  const token = await signToken("s", {
    runner: "runner/1.0.0", layers: [], pack: "packs/catalog/a/1.0.0", name: "A", exp: 4e9,
  });
  const response = await call(`/d/${token}`, { BUCKET: empty, DOWNLOAD_TOKEN_SECRET: "s" });
  assert.equal(response.status, 503);
  assert.match(await response.text(), /being updated/);
});
