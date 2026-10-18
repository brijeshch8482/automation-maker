import assert from "node:assert/strict";
import { test } from "node:test";
import { signToken, verifyToken, TokenError } from "../src/token.js";

const payload = {
  runner: "runner/1.0.0",
  layers: ["layers/openpyxl/3.1.5"],
  pack: "packs/catalog/make-pdf/1.0.0",
  name: "MakePDF",
  exp: 2_000_000_000,
};

test("a signed token verifies and returns its payload", async () => {
  const token = await signToken("s3cret", payload);
  assert.deepEqual(await verifyToken("s3cret", token, 1_900_000_000), { kind: "zip", ...payload });
});

test("a bundle token has no runner", async () => {
  const { runner, ...rest } = payload;
  const bundle = { kind: "bundle", ...rest };
  assert.deepEqual(await verifyToken("s3cret", await signToken("s3cret", bundle), 0), bundle);
  for (const bad of [{ ...bundle, runner }, { ...bundle, kind: "other" }, rest]) {
    await assert.rejects(verifyToken("s3cret", await signToken("s3cret", bad), 0), /bad payload/);
  }
});

test("wrong secret, edited payload, expired or malformed tokens are refused", async () => {
  const token = await signToken("s3cret", payload);
  await assert.rejects(verifyToken("other", token, 0), TokenError);
  const [body, mac] = token.split(".");
  const edited = Buffer.from(JSON.stringify({ ...payload, name: "Evil" })).toString("base64url");
  await assert.rejects(verifyToken("s3cret", `${edited}.${mac}`, 0), /bad signature/);
  await assert.rejects(verifyToken("s3cret", token, 2_000_000_001), /expired/);
  for (const bad of ["", "abc", `${body}.${mac}.x`, `${body}.`]) {
    await assert.rejects(verifyToken("s3cret", bad, 0), TokenError);
  }
  await assert.rejects(verifyToken("", token, 0), /not configured/);
});

test("only known R2 prefixes and plain app names", async () => {
  for (const change of [
    { runner: "runner/../secrets" },
    { pack: "catalog/manifest.json" },
    { pack: "packs/jobs/job_x/attempt-1" },
    { layers: ["layers/../../x/1"] },
    { layers: "layers/a/1" },
    { name: "Make PDF" },
    { name: "a/b" },
  ]) {
    const token = await signToken("s3cret", { ...payload, ...change });
    await assert.rejects(verifyToken("s3cret", token, 0), /bad payload/, JSON.stringify(change));
  }
});
