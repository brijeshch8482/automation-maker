// Download tokens, made by the API (api/downloads.py): base64url(payload) "." base64url(HMAC).
// HMAC-SHA256 with DOWNLOAD_TOKEN_SECRET over the payload part. The API decides what goes into
// a download; the Worker only checks the token and streams exactly that.

const RUNNER = /^runner\/\d+\.\d+\.\d+$/;
const LAYER = /^layers\/[A-Za-z0-9_.]+\/[A-Za-z0-9_.+!]+$/;
const PACK = /^packs\/(catalog\/[a-z0-9]+(-[a-z0-9]+)*\/\d+\.\d+\.\d+|jobs\/job_[0-9A-Z]{26}\/attempt-\d{1,2})$/;
const NAME = /^[A-Za-z0-9]{1,40}$/;
const MAX_LAYERS = 50;

export class TokenError extends Error {}

const encoder = new TextEncoder();

export function base64url(bytes) {
  let text = "";
  for (const b of bytes) text += String.fromCharCode(b);
  return btoa(text).replaceAll("+", "-").replaceAll("/", "_").replace(/=+$/, "");
}

function fromBase64url(text) {
  const padded = text.replaceAll("-", "+").replaceAll("_", "/") + "===".slice((text.length + 3) % 4);
  return Uint8Array.from(atob(padded), (c) => c.charCodeAt(0));
}

async function hmacKey(secret) {
  return crypto.subtle.importKey("raw", encoder.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, [
    "sign",
    "verify",
  ]);
}

export async function signToken(secret, payload) {
  const body = base64url(encoder.encode(JSON.stringify(payload)));
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", await hmacKey(secret), encoder.encode(body)));
  return `${body}.${base64url(mac)}`;
}

/** The checked payload: {runner, layers, pack, name, exp}. Throws TokenError otherwise. */
export async function verifyToken(secret, token, now = Date.now() / 1000) {
  if (!secret) throw new TokenError("not configured");
  const [body, mac, extra] = String(token || "").split(".");
  if (!body || !mac || extra !== undefined) throw new TokenError("malformed");
  let ok = false;
  try {
    ok = await crypto.subtle.verify("HMAC", await hmacKey(secret), fromBase64url(mac), encoder.encode(body));
  } catch {
    ok = false;
  }
  if (!ok) throw new TokenError("bad signature");
  let payload;
  try {
    payload = JSON.parse(new TextDecoder().decode(fromBase64url(body)));
  } catch {
    throw new TokenError("malformed");
  }
  const { runner, layers, pack, name, exp } = payload;
  if (typeof exp !== "number" || exp < now) throw new TokenError("expired");
  if (!RUNNER.test(runner) || !PACK.test(pack) || !NAME.test(name)) throw new TokenError("bad payload");
  if (!Array.isArray(layers) || layers.length > MAX_LAYERS || !layers.every((l) => LAYER.test(l))) {
    throw new TokenError("bad payload");
  }
  return { runner, layers, pack, name, exp };
}
