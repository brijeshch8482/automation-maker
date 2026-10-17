// node test/harness.mjs <r2 folder> <secret> <token> <out.zip>: run the Worker once, as the
// pytest integration test (tests/packaging/test_zipblocks.py) does. Prints {status, headers}.
import { writeFileSync } from "node:fs";
import { handle } from "../src/index.js";
import { folderBucket } from "./fake-bucket.js";

const [root, secret, token, out] = process.argv.slice(2);
const env = { BUCKET: folderBucket(root), DOWNLOAD_TOKEN_SECRET: secret };
const pending = [];
const response = await handle(new Request(`https://dl.example/d/${token}`), env, {
  waitUntil: (p) => pending.push(p),
});
const body = new Uint8Array(await response.arrayBuffer());
await Promise.all(pending);
writeFileSync(out, body);
console.log(JSON.stringify({ status: response.status, headers: Object.fromEntries(response.headers), bytes: body.length }));
