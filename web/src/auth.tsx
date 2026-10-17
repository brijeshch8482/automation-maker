// Login. Supabase email magic links in deployment; a dev-only "sign in as <name>" when
// VITE_DEV_AUTH=true (the API accepts "Bearer dev:<name>" only with its own DEV_AUTH on).

import type { SupabaseClient } from "@supabase/supabase-js";
import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { devAuthEnabled, supabaseConfig } from "./env";

export type AuthMode = "supabase" | "dev" | "none";

export interface Session {
  userId: string;
  label: string; // email or dev name, for the header
}

interface AuthValue {
  mode: AuthMode;
  session: Session | null;
  loading: boolean;
  signInWithEmail: (email: string) => Promise<void>;
  devSignIn: (name: string) => void;
  signOut: () => Promise<void>;
}

const DEV_USER_KEY = "makemyexe.devUser";

let supabase: Promise<SupabaseClient> | null = null;

export function authMode(): AuthMode {
  if (supabaseConfig()) return "supabase";
  if (devAuthEnabled()) return "dev";
  return "none";
}

/** Loaded on demand so the catalog doesn't pay for the Supabase bundle. */
function supabaseClient(): Promise<SupabaseClient> {
  const config = supabaseConfig();
  if (!config) return Promise.reject(new Error("Supabase is not configured"));
  supabase ??= import("@supabase/supabase-js").then(({ createClient }) =>
    createClient(config.url, config.anonKey),
  );
  return supabase;
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

  useEffect(() => {
    if (mode !== "supabase") return;
    const toSession = (s: { user: { id: string; email?: string } } | null): Session | null =>
      s ? { userId: s.user.id, label: s.user.email ?? "Signed in" } : null;
    let unsubscribe = () => {};
    let cancelled = false;
    void supabaseClient().then(async (client) => {
      if (cancelled) return;
      const { data } = client.auth.onAuthStateChange((_event, s) => setSession(toSession(s)));
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
      async signInWithEmail(email) {
        const { error } = await (await supabaseClient()).auth.signInWithOtp({
          email,
          options: { emailRedirectTo: window.location.href },
        });
        if (error) throw error;
      },
      devSignIn(name) {
        writeDevUser(name);
        setSession({ userId: name, label: name });
      },
      async signOut() {
        if (mode === "supabase") await (await supabaseClient()).auth.signOut();
        writeDevUser(null);
        setSession(null);
      },
    }),
    [mode, session, loading],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside <AuthProvider>");
  return value;
}
