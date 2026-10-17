// Login. In deployment, Supabase Auth: email + password, a 6-digit code by email, and Google
// (VITE_SUPABASE_ANON_KEY holds the project's publishable key, sb_publishable_...; supabase-js sends
// it as `apikey`, never as a Bearer token). Every method ends in the same Supabase session, so the
// API needs nothing per method. A dev-only "sign in as <name>" when VITE_DEV_AUTH=true (the API
// accepts "Bearer dev:<name>" only with its own DEV_AUTH on).

import type { SupabaseClient } from "@supabase/supabase-js";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { devAuthEnabled, supabaseConfig } from "./env";

export type AuthMode = "supabase" | "dev" | "none";

export interface Session {
  userId: string;
  label: string; // email or dev name, for the header
}

/** Which sign-in methods the Supabase project has switched on (its public /auth/v1/settings). */
export interface AuthProviders {
  google: boolean;
  signupAllowed: boolean;
}

/** What a code from an email is for; matches Supabase's verifyOtp types. */
export type CodePurpose = "email" | "signup" | "recovery";

export interface SignUpResult {
  /** False when the project confirms emails: the user must enter the code we sent first. */
  signedIn: boolean;
}

interface AuthValue {
  mode: AuthMode;
  session: Session | null;
  loading: boolean;
  /** Set after the user opened a password-reset link: the login page asks for a new password. */
  recovering: boolean;
  signInWithPassword: (email: string, password: string) => Promise<void>;
  signUp: (email: string, password: string) => Promise<SignUpResult>;
  /** Email a 6-digit sign-in code (the same email also holds a link). Creates the account if new. */
  sendEmailCode: (email: string) => Promise<void>;
  resendSignupCode: (email: string) => Promise<void>;
  sendPasswordReset: (email: string) => Promise<void>;
  verifyCode: (email: string, code: string, purpose: CodePurpose) => Promise<void>;
  setNewPassword: (password: string) => Promise<void>;
  /** Leaves the site for Google; Supabase sends the user back to `returnTo` on this site. */
  signInWithGoogle: (returnTo: string) => Promise<void>;
  devSignIn: (name: string) => void;
  signOut: () => Promise<void>;
}

const DEV_USER_KEY = "makemyexe.devUser";

let supabase: { config: string; client: Promise<SupabaseClient> } | null = null;

export function authMode(): AuthMode {
  if (supabaseConfig()) return "supabase";
  if (devAuthEnabled()) return "dev";
  return "none";
}

/** Loaded on demand so the catalog doesn't pay for the Supabase bundle. */
function supabaseClient(): Promise<SupabaseClient> {
  const config = supabaseConfig();
  if (!config) return Promise.reject(new Error("Supabase is not configured"));
  const key = `${config.url} ${config.anonKey}`;
  if (supabase?.config !== key) {
    supabase = {
      config: key,
      client: import("@supabase/supabase-js").then(({ createClient }) =>
        // PKCE: Google sends back a one-time code instead of putting tokens in the URL.
        createClient(config.url, config.anonKey, { auth: { flowType: "pkce" } }),
      ),
    };
  }
  return supabase.client;
}

let providers: Promise<AuthProviders> | null = null;

/** Read once per page load; on any failure assume only email sign-in (never show a dead button). */
export function authProviders(): Promise<AuthProviders> {
  const config = supabaseConfig();
  if (!config) return Promise.resolve({ google: false, signupAllowed: false });
  providers ??= fetch(`${config.url}/auth/v1/settings`, { headers: { apikey: config.anonKey } })
    .then((r) => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
    .then((data: { external?: Record<string, boolean>; disable_signup?: boolean }) => ({
      google: data.external?.google === true,
      signupAllowed: data.disable_signup !== true,
    }))
    .catch(() => ({ google: false, signupAllowed: true }));
  return providers;
}

/** For tests: forget the cached client and provider settings. */
export function resetAuthForTests(): void {
  supabase = null;
  providers = null;
}

/** Supabase errors in plain words; unknown ones keep Supabase's own message. */
export function authErrorMessage(error: { message?: string; code?: string; status?: number }): string {
  const code = error.code ?? "";
  const message = error.message ?? "";
  if (code === "invalid_credentials" || /invalid login credentials/i.test(message)) {
    return "That email and password don't match. Try again, or sign in with an email code.";
  }
  if (code === "email_not_confirmed" || /email not confirmed/i.test(message)) {
    return "Please confirm your email first: enter the code we sent you, or sign in with an email code.";
  }
  if (code === "user_already_exists" || /already registered/i.test(message)) {
    return "There's already an account with this email. Sign in instead.";
  }
  if (code === "otp_expired" || /token has expired|token is invalid|invalid otp/i.test(message)) {
    return "That code is wrong or has expired. Check the latest email, or send a new code.";
  }
  if (code === "weak_password" || /password should/i.test(message)) {
    return "Choose a stronger password: at least 8 characters, not a common one.";
  }
  if (code === "over_email_send_rate_limit" || error.status === 429) {
    return "Too many emails in a short time. Wait a minute, then try again.";
  }
  if (/provider is not enabled/i.test(message)) return "Google sign-in isn't switched on yet.";
  return message || "Something went wrong. Please try again.";
}

class AuthError extends Error {}

function check(result: { error: { message?: string; code?: string; status?: number } | null }): void {
  if (result.error) throw new AuthError(authErrorMessage(result.error));
}

function readDevUser(): string | null {
  try {
    return localStorage.getItem(DEV_USER_KEY);
  } catch {
    return null;
  }
}

function writeDevUser(name: string | null): void {
  try {
    if (name) localStorage.setItem(DEV_USER_KEY, name);
    else localStorage.removeItem(DEV_USER_KEY);
  } catch {
    // Private mode or blocked storage: the dev login just won't persist.
  }
}

/** Bearer token for API calls, or null when signed out. */
export async function getAccessToken(): Promise<string | null> {
  const mode = authMode();
  if (mode === "supabase") {
    const { data } = await (await supabaseClient()).auth.getSession();
    return data.session?.access_token ?? null;
  }
  if (mode === "dev") {
    const user = readDevUser();
    return user ? `dev:${user}` : null;
  }
  return null;
}

const AuthContext = createContext<AuthValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const mode = authMode();
  const [session, setSession] = useState<Session | null>(() => {
    const user = mode === "dev" ? readDevUser() : null;
    return user ? { userId: user, label: user } : null;
  });
  const [loading, setLoading] = useState(mode === "supabase");
  const [recovering, setRecovering] = useState(false);

  useEffect(() => {
    if (mode !== "supabase") return;
    const toSession = (s: { user: { id: string; email?: string } } | null): Session | null =>
      s ? { userId: s.user.id, label: s.user.email ?? "Signed in" } : null;
    let unsubscribe = () => {};
    let cancelled = false;
    void supabaseClient().then(async (client) => {
      if (cancelled) return;
      const { data } = client.auth.onAuthStateChange((event, s) => {
        setSession(toSession(s));
        if (event === "PASSWORD_RECOVERY") setRecovering(true);
      });
      unsubscribe = () => data.subscription.unsubscribe();
      const { data: current } = await client.auth.getSession();
      if (!cancelled) {
        setSession(toSession(current.session));
        setLoading(false);
      }
    });
    return () => {
      cancelled = true;
      unsubscribe();
    };
  }, [mode]);

  const value = useMemo<AuthValue>(
    () => ({
      mode,
      session,
      loading,
      recovering,
      async signInWithPassword(email, password) {
        check(await (await supabaseClient()).auth.signInWithPassword({ email, password }));
      },
      async signUp(email, password) {
        const result = await (await supabaseClient()).auth.signUp({
          email,
          password,
          options: { emailRedirectTo: window.location.origin },
        });
        check(result);
        return { signedIn: result.data.session !== null };
      },
      async sendEmailCode(email) {
        check(
          await (await supabaseClient()).auth.signInWithOtp({
            email,
            // The email also holds a link back to the site root, which must be listed in
            // Supabase > Auth > URL Configuration (docs/DEPLOY.md).
            options: { emailRedirectTo: window.location.origin },
          }),
        );
      },
      async resendSignupCode(email) {
        check(await (await supabaseClient()).auth.resend({ type: "signup", email }));
      },
      async sendPasswordReset(email) {
        check(
          await (await supabaseClient()).auth.resetPasswordForEmail(email, {
            redirectTo: `${window.location.origin}/login`,
          }),
        );
      },
      async verifyCode(email, code, purpose) {
        check(await (await supabaseClient()).auth.verifyOtp({ email, token: code, type: purpose }));
      },
      async setNewPassword(password) {
        check(await (await supabaseClient()).auth.updateUser({ password }));
        setRecovering(false);
      },
      async signInWithGoogle(returnTo) {
        check(
          await (await supabaseClient()).auth.signInWithOAuth({
            provider: "google",
            options: { redirectTo: `${window.location.origin}${returnTo}` },
          }),
        );
      },
      devSignIn(name) {
        writeDevUser(name);
        setSession({ userId: name, label: name });
      },
      async signOut() {
        if (mode === "supabase") await (await supabaseClient()).auth.signOut();
        writeDevUser(null);
        setSession(null);
        setRecovering(false);
      },
    }),
    [mode, session, loading, recovering],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
