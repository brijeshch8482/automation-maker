// Sign-in with Supabase: the real supabase-js against a fake Supabase Auth server, so the tests
// check the requests a browser would really send.

import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi } from "vitest";

import { authErrorMessage } from "../auth";
import { renderAt } from "../test/helpers";

const SUPABASE = "https://project.supabase.test";
const KEY = "sb_publishable_test123";

interface Request {
  method: string;
  path: string;
  query: URLSearchParams;
  body: Record<string, unknown>;
  apikey: string | null;
}

type Reply = { status?: number; body?: unknown };

function session(email = "asha@example.com") {
  const now = Math.floor(Date.now() / 1000);
  return {
    access_token: "header.payload.signature",
    token_type: "bearer",
    expires_in: 3600,
    expires_at: now + 3600,
    refresh_token: "refresh",
    user: { id: "user-1", email, aud: "authenticated", role: "authenticated", app_metadata: {}, user_metadata: {}, created_at: "2026-10-17T00:00:00Z" },
  };
}

/** A tiny Supabase Auth. `routes` override replies by "METHOD /path". */
function fakeSupabase(routes: Record<string, Reply> = {}, settings: unknown = { external: { google: true, email: true }, disable_signup: false }) {
  vi.stubEnv("VITE_API_URL", "http://api.test");
  vi.stubEnv("VITE_SUPABASE_URL", SUPABASE);
  vi.stubEnv("VITE_SUPABASE_ANON_KEY", KEY);
  const requests: Request[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init: RequestInit = {}) => {
      const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.href : input.url);
      const method = init.method ?? "GET";
      if (url.host === "api.test") {
        return new Response("[]", { status: 200, headers: { "Content-Type": "application/json" } }); // no jobs yet
      }
      const path = url.pathname.replace("/auth/v1", "");
      const request: Request = {
        method,
        path,
        query: url.searchParams,
        body: init.body ? JSON.parse(init.body as string) : {},
        apikey: new Headers(init.headers).get("apikey"),
      };
      requests.push(request);
      const reply: Reply = routes[`${method} ${path}`] ??
        (path === "/settings" ? { body: settings } : { body: {} });
      return new Response(JSON.stringify(reply.body ?? {}), {
        status: reply.status ?? 200,
        headers: { "Content-Type": "application/json" },
      });
    }),
  );
  return requests;
}

const find = (requests: Request[], method: string, path: string) =>
  requests.find((r) => r.method === method && r.path === path);

test("password sign-in, then on to the page that asked for it", async () => {
  const requests = fakeSupabase({ "POST /token": { body: session() } });
  const user = userEvent.setup();
  renderAt("/login?next=/custom");
  expect(await screen.findByRole("heading", { name: "Sign in to MakeMyEXE" })).toBeTruthy();
  expect(screen.getByRole("tab", { name: "Password" })).toHaveProperty("ariaSelected", "true");

  await user.type(screen.getByLabelText("Email"), "asha@example.com");
  await user.type(screen.getByLabelText("Password"), "correct horse");
  await user.click(screen.getByRole("button", { name: "Sign in" }));

  expect(await screen.findByRole("heading", { name: "Describe your automation" })).toBeTruthy();
  const token = find(requests, "POST", "/token")!;
  expect(token.query.get("grant_type")).toBe("password");
  expect(token.body).toMatchObject({ email: "asha@example.com", password: "correct horse" });
  expect(token.apikey).toBe(KEY);
  expect(screen.getByRole("button", { name: "Account" }).textContent).toBe("a");
});

test("a wrong password gets a plain message", async () => {
  fakeSupabase({
    "POST /token": { status: 400, body: { code: "invalid_credentials", msg: "Invalid login credentials" } },
  });
  const user = userEvent.setup();
  renderAt("/login");
  await user.type(await screen.findByLabelText("Email"), "asha@example.com");
  await user.type(screen.getByLabelText("Password"), "wrong");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  expect((await screen.findByRole("alert")).textContent).toMatch(/email and password don't match/);
});

test("email code: send, then verify the 6 digits", async () => {
  const requests = fakeSupabase({ "POST /verify": { body: session() } });
  const user = userEvent.setup();
  renderAt("/login");
  await user.click(await screen.findByRole("tab", { name: "Email code" }));
  expect(screen.queryByLabelText("Password")).toBeNull();
  await user.type(screen.getByLabelText("Email"), "asha@example.com");
  await user.click(screen.getByRole("button", { name: "Email me a code" }));

  expect(await screen.findByRole("heading", { name: "Check your email" })).toBeTruthy();
  const otp = find(requests, "POST", "/otp")!;
  expect(otp.body).toMatchObject({ email: "asha@example.com", create_user: true });
  expect(otp.query.get("redirect_to")).toBe(window.location.origin);
  expect(screen.getByText(/new code in \d+ s/)).toBeTruthy(); // no resend spam

  const code = screen.getByLabelText("Code");
  expect(code.getAttribute("autocomplete")).toBe("one-time-code");
  await user.type(code, "12a34 56"); // only digits are kept
  expect(code).toHaveProperty("value", "123456");
  await user.click(screen.getByRole("button", { name: "Sign in" }));

  expect(await screen.findByRole("heading", { name: "My apps" })).toBeTruthy();
  expect(find(requests, "POST", "/verify")!.body).toMatchObject({
    email: "asha@example.com",
    token: "123456",
    type: "email",
  });
});

test("sign up with a password, confirm with the code", async () => {
  const user1 = session("new@example.com").user;
  const requests = fakeSupabase({
    "POST /signup": { body: user1 }, // email confirmation on: a user, no session yet
    "POST /verify": { body: session("new@example.com") },
  });
  const user = userEvent.setup();
  renderAt("/login");
  await user.click(await screen.findByRole("button", { name: "Create an account" }));
  expect(screen.getByRole("heading", { name: "Create your account" })).toBeTruthy();

  await user.type(screen.getByLabelText("Email"), "new@example.com");
  await user.type(screen.getByLabelText("Password"), "short");
  expect(screen.getByText("At least 8 characters")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Create account" })).toHaveProperty("disabled", true);
  await user.type(screen.getByLabelText("Password"), "-but-longer");
  await user.click(screen.getByRole("button", { name: "Show password" }));
  expect(screen.getByLabelText("Password")).toHaveProperty("type", "text");
  await user.click(screen.getByRole("button", { name: "Create account" }));

  expect(await screen.findByRole("heading", { name: "Confirm your email" })).toBeTruthy();
  expect(find(requests, "POST", "/signup")!.body).toMatchObject({ email: "new@example.com", password: "short-but-longer" });
  await user.type(screen.getByLabelText("Code"), "654321");
  await user.click(screen.getByRole("button", { name: "Confirm and continue" }));
  await waitFor(() => expect(find(requests, "POST", "/verify")?.body).toMatchObject({ type: "signup", token: "654321" }));
  expect(await screen.findByRole("heading", { name: "My apps" })).toBeTruthy();
});

test("forgot password: code, then a new password", async () => {
  const requests = fakeSupabase({
    "POST /verify": { body: session() },
    "PUT /user": { body: session().user },
  });
  const user = userEvent.setup();
  renderAt("/login");
  await user.click(await screen.findByRole("button", { name: "Forgot password?" }));
  await user.type(screen.getByLabelText("Email"), "asha@example.com");
  await user.click(screen.getByRole("button", { name: "Send reset code" }));
  expect(await screen.findByRole("heading", { name: "Reset your password" })).toBeTruthy();
  expect(find(requests, "POST", "/recover")!.body).toMatchObject({ email: "asha@example.com" });

  await user.type(screen.getByLabelText("Code"), "111222");
  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(await screen.findByRole("heading", { name: "Choose a new password" })).toBeTruthy();
  await user.type(screen.getByLabelText("New password"), "a-new-password");
  await user.click(screen.getByRole("button", { name: "Save password and continue" }));

  expect(await screen.findByRole("heading", { name: "My apps" })).toBeTruthy();
  expect(find(requests, "PUT", "/user")!.body).toMatchObject({ password: "a-new-password" });
});

test("Google button shows only when Google is switched on in Supabase", async () => {
  fakeSupabase();
  renderAt("/login");
  expect(await screen.findByRole("button", { name: "Continue with Google" })).toBeTruthy();
});

test("no Google button when it is off, or when the settings can't be read", async () => {
  fakeSupabase({}, { external: { google: false } });
  renderAt("/login");
  expect(await screen.findByRole("heading", { name: "Sign in to MakeMyEXE" })).toBeTruthy();
  await new Promise((r) => setTimeout(r, 50));
  expect(screen.queryByRole("button", { name: "Continue with Google" })).toBeNull();
});

test("an error coming back from Google is shown", async () => {
  fakeSupabase();
  renderAt("/login?error=access_denied&error_description=The+user+cancelled");
  expect((await screen.findByRole("alert")).textContent).toMatch(/Sign-in didn't finish: The user cancelled/);
});

test("signing out from the account menu", async () => {
  fakeSupabase({ "POST /token": { body: session() }, "POST /logout": { status: 204 } });
  const user = userEvent.setup();
  renderAt("/login");
  await user.type(await screen.findByLabelText("Email"), "asha@example.com");
  await user.type(screen.getByLabelText("Password"), "correct horse");
  await user.click(screen.getByRole("button", { name: "Sign in" }));
  await user.click(await screen.findByRole("button", { name: "Account" }));
  expect(screen.getByRole("menu").textContent).toContain("asha@example.com");
  await user.click(screen.getByRole("menuitem", { name: "Sign out" }));
  expect(await screen.findByText("Sign in to make and follow custom automations.")).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Account" })).toBeNull();
});

test("Supabase errors read as plain words", () => {
  expect(authErrorMessage({ code: "otp_expired", message: "Token has expired or is invalid" })).toMatch(/wrong or has expired/);
  expect(authErrorMessage({ code: "user_already_exists", message: "User already registered" })).toMatch(/Sign in instead/);
  expect(authErrorMessage({ status: 429, message: "rate limit" })).toMatch(/Too many emails/);
  expect(authErrorMessage({ message: "Something new" })).toBe("Something new");
});
