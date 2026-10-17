// Build-time configuration (Vite env vars). Read through functions so tests can stub them.

/** FastAPI base URL. Empty: catalog from the bundled spec files, custom jobs unavailable. */
export function apiUrl(): string {
  return (import.meta.env.VITE_API_URL ?? "").replace(/\/+$/, "");
}

export function supabaseConfig(): { url: string; anonKey: string } | null {
  const url = import.meta.env.VITE_SUPABASE_URL ?? "";
  const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY ?? "";
  return url && anonKey ? { url, anonKey } : null;
}

/** Dev-only login by name; matches the API's DEV_AUTH mode. Never enable in production. */
export function devAuthEnabled(): boolean {
  return import.meta.env.VITE_DEV_AUTH === "true";
}
